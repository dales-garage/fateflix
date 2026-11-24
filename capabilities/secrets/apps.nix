{ pkgs }:
let
  python = pkgs.python3;
  provision = name: {
    type = "app";
    meta.description = "Resolve role-specific SecretSpec credentials and install atomically";
    program = pkgs.lib.getExe (
      pkgs.writeShellApplication {
        inherit name;
        runtimeInputs = [
          pkgs.secretspec
          (import ./pass.nix { inherit pkgs; })
          pkgs.passage
          pkgs.age
        ];
        text = ''
          if [[ "''${1:-}" == "--help" ]]; then
            echo "Run as marty on nixflix; installed /etc/nixflix/mode selects the namespace. The pass provider uses age-backed Passage."
            exit 0
          fi
          exec ${python}/bin/python3 ${./.}/provision.py ${name}
        '';
      }
    );
  };
in
builtins.listToAttrs (
  map
    (name: {
      inherit name;
      value = provision name;
    })
    [
      "provision"
      "provision-notifications"
      "provision-notifiarr"
    ]
)
// {
  migrate-secrets-to-passage = {
    type = "app";
    meta.description = "Migrate and verify the GPG vault without deleting its entries";
    program = pkgs.lib.getExe (
      pkgs.writeShellApplication {
        name = "migrate-secrets-to-passage";
        runtimeInputs = [
          pkgs.pass
          pkgs.gnupg
          pkgs.passage
          pkgs.age
        ];
        text = ''
          exec ${python}/bin/python3 ${./.}/passage_store.py --legacy-pass ${pkgs.pass}/bin/pass "$@"
        '';
      }
    );
  };
}
