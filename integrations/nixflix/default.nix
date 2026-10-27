{ pkgs, src }:
let
  clean =
    path:
    pkgs.lib.cleanSourceWith {
      src = path;
      filter =
        file: _:
        !(builtins.elem (builtins.baseNameOf file) [
          "__pycache__"
          ".source-cache"
        ]);
    };
in
pkgs.applyPatches {
  name = "fateflix-nixflix-source";
  inherit src;
  patches = [
    ./patches/arr-runtime-credentials.patch
    ./patches/four-instance-integrations.patch
    ./patches/notification-reconciliation.patch
  ];
  postPatch = ''
    cp -R ${clean ./vendor/modules}/. modules/
    cp -R ${clean ./compatibility}/. modules/
    # The retained plugin modules and their public source-spec helper share an
    # API; upstream may evolve its helper independently of these adaptations.
    cp ${../../lib/jellyfin-plugins.nix} lib/jellyfin-plugins.nix
    mkdir -p modules/jellyfin/plugins modules/navidrome/plugins
    cp -R ${clean ./plugins/jellyfin}/. modules/jellyfin/plugins/
    cp -R ${clean ./plugins/navidrome}/. modules/navidrome/plugins/
    substituteInPlace modules/navidrome/plugins/default.nix \
      --replace-fail './fromGenerated.nix' './fromGenerated.nix ./runtime.nix'
    cp -R ${clean ../../pkgs}/. pkgs/
    chmod -R u+w .
  '';
}
