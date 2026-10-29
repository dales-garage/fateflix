{ pkgs, self }:
let
  python = pkgs.python3.withPackages (p: [
    p.configobj
    p.pyyaml
  ]);
in
{
  type = "app";
  meta.description = "Manual archive of the completed Ubuntu migration; never scheduled";
  program = pkgs.lib.getExe (
    pkgs.writeShellApplication {
      name = "legacy-ubuntu-migration";
      runtimeInputs = [
        pkgs.openssh
        pkgs.systemd
        pkgs.pass
        pkgs.gnupg
      ];
      text = ''
        exec ${python}/bin/python3 ${self}/legacy/ubuntu-migration/run.py "$@"
      '';
    }
  );
}
