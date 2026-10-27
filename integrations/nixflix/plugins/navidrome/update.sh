#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
PLUGINS_DIR="$REPO_ROOT/integrations/nixflix/plugins/navidrome"
GEN_DIR="$PLUGINS_DIR/gen"
SYSTEM="x86_64-linux"

echo "=== Updating Navidrome plugins ==="

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT
FAILED=()

cat > "$WORKDIR/discover.nix" <<EOF
let
  flake = builtins.getFlake "$REPO_ROOT";
  eval = import "\${flake.inputs.nixpkgs}/nixos/lib/eval-config.nix" {
    system = "$SYSTEM";
    modules = [
      flake.nixosModules.default
      {
        nixflix.enable = true;
        nixflix.navidrome.enable = true;
        nixflix.navidrome.users.admin = { isAdmin = true; password = "x"; };
        fileSystems."/" = { device = "/dev/null"; fsType = "ext4"; };
        boot.loader.grub.device = "/dev/null";
      }
    ];
  };
  plugins = eval.config.nixflix.navidrome.plugins;
  firstClass = builtins.filter (name: plugins.\${name}.package != null) (builtins.attrNames plugins);
in
builtins.listToAttrs (map (name: {
  inherit name;
  value = {
    drvPath = plugins.\${name}.package.drvPath;
    apiId = plugins.\${name}.apiId;
    # Real id navidrome assembles with, not necessarily the plugin's own standalone build output name.
    realBundleName = plugins.\${name}.package.bundleName or plugins.\${name}.package.pname;
  };
}) firstClass)
EOF

# {"apple-music": {"drvPath": "/nix/store/...drv", "apiId": "apple-music", "realBundleName": "apple-music"}, ...}
PLUGINS_JSON=$(nix eval --json --impure -f "$WORKDIR/discover.nix")

# Keep the existing generation intact if any package or manifest fails.
mkdir -p "$WORKDIR/gen"

for plugin_name in $(echo "$PLUGINS_JSON" | jq -r 'keys[]'); do
  echo "--- $plugin_name ---"
  drv_path=$(echo "$PLUGINS_JSON" | jq -r --arg n "$plugin_name" '.[$n].drvPath')
  configured_api_id=$(echo "$PLUGINS_JSON" | jq -r --arg n "$plugin_name" '.[$n].apiId')
  real_bundle_name=$(echo "$PLUGINS_JSON" | jq -r --arg n "$plugin_name" '.[$n].realBundleName')

  if ! OUT_PATH=$(nix build "${drv_path}^out" --no-link --print-out-paths 2>"$WORKDIR/build.log"); then
    echo "  Build failed for $plugin_name:" >&2
    cat "$WORKDIR/build.log" >&2
    FAILED+=("$plugin_name")
    continue
  fi

  # Older pins install directly in share; newer Nixpkgs uses share/plugins.
  mapfile -d '' -t bundles < <(find "$OUT_PATH/share" -maxdepth 2 -name '*.ndp' -print0)
  if [ "${#bundles[@]}" -ne 1 ]; then
    echo "  Expected one .ndp under $OUT_PATH/share, found ${#bundles[@]}" >&2
    FAILED+=("$plugin_name")
    continue
  fi
  NDP_FILE="${bundles[0]}"

  plugin_id="$real_bundle_name"
  if [ "$plugin_id" != "$configured_api_id" ]; then
    echo "  WARNING: real bundleName is '$plugin_id' but default.nix's apiId is '$configured_api_id' -- update default.nix" >&2
  fi
  # Python is already in the development shell; no ambient unzip is required.
  manifest_json=$(python3 -c 'import sys, zipfile; print(zipfile.ZipFile(sys.argv[1]).read("manifest.json").decode("utf-8"))' "$NDP_FILE")
  schema_json=$(echo "$manifest_json" | jq -c '.config.schema // {}')
  description=$(echo "$manifest_json" | jq -r '.description // .name // empty')

  jq -n --arg pluginName "$plugin_name" --arg pluginId "$plugin_id" \
        --arg description "$description" --argjson schema "$schema_json" \
        '{pluginName: $pluginName, pluginId: $pluginId, description: $description, schema: $schema}' \
        > "$WORKDIR/input.json"

  OUT_FILE="$WORKDIR/gen/${plugin_name}-plugin.nix"

  if ! nix eval --raw --impure --expr "
        let
          lib = (builtins.getFlake \"$REPO_ROOT\").inputs.nixpkgs.lib;
          gen = import ${REPO_ROOT}/integrations/nixflix/vendor/modules/navidrome/plugins/schemaToOptions.nix { inherit lib; };
          input = builtins.fromJSON (builtins.readFile \"$WORKDIR/input.json\");
        in gen.mkPluginFile input
      " > "$OUT_FILE.tmp" 2>"$WORKDIR/eval.log"; then
    echo "  Codegen failed for $plugin_name:" >&2
    cat "$WORKDIR/eval.log" >&2
    rm -f "$OUT_FILE.tmp"
    FAILED+=("$plugin_name")
    continue
  fi

  mv "$OUT_FILE.tmp" "$OUT_FILE"
  echo "  Wrote $OUT_FILE (built api id: $plugin_id)"
done

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo ""
  echo "ERROR: failed to regenerate: ${FAILED[*]}" >&2
  exit 1
fi

# Publish only a complete generation, including removal of dropped plugins.
mkdir -p "$GEN_DIR"
rm -f "$GEN_DIR"/*-plugin.nix
find "$WORKDIR/gen" -maxdepth 1 -name '*-plugin.nix' -exec mv -t "$GEN_DIR" -- {} +

echo "Done."
