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
          pkgs.pass
          pkgs.gnupg
        ];
        text = ''
          if [[ "''${1:-}" == "--help" ]]; then
            echo "Run as marty on nixflix; installed /etc/nixflix/mode selects the namespace. SECRETSPEC_PROVIDER defaults to pass."
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
