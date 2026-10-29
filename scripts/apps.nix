{ pkgs, self }:
let
  python = pkgs.python3.withPackages (p: [
    p.configobj
    p.pyyaml
  ]);
  app = name: runtimeInputs: text: {
    type = "app";
    meta.description = "NixFlix ${builtins.replaceStrings [ "-" ] [ " " ] name} operation";
    program = pkgs.lib.getExe (pkgs.writeShellApplication { inherit name runtimeInputs text; });
  };
  script =
    name: dependencies:
    app name dependencies ''
      exec ${python}/bin/python3 ${self}/scripts/${name}.py "$@"
    '';

in
{
  update-extra-dependencies =
    app "update-extra-dependencies"
      [
        pkgs.git
        pkgs.nix
        pkgs.skopeo
        pkgs.bash
        pkgs.jq
        pkgs.curl
        pkgs.coreutils
        pkgs.findutils
      ]
      ''
        exec ${python}/bin/python3 ${self}/scripts/extra_dependencies.py "$@"
      '';
  deploy = script "deploy" [
    pkgs.jujutsu
    pkgs.openssh
  ];
  snapshot = (script "snapshot" [ ]) // {
    meta.description = "Migration-only Ubuntu state snapshot; all declared source directories are required";
  };
  cutover-source = script "cutover-source" [ pkgs.openssh ];
  migrate-native = script "migrate-native" [ pkgs.systemd ];
  route-seerr = script "route-seerr" [ pkgs.openssh ];
  router-dns = script "router-dns" [ pkgs.openssh ];
  router-https = script "router-https" [ pkgs.openssh ];
  public-dns = script "public-dns" [ pkgs.openssh ];
  plex-remote = script "plex-remote" [ ];
  verify-production = script "verify-production" [
    pkgs.systemd
    pkgs.util-linux
  ];
  restore = script "restore" [ pkgs.systemd ];
  reassign-profiles = script "reassign-profiles" [ ];
  validate-state = script "validate-state" [ ];
  test-isolation = script "test-isolation" [
    pkgs.systemd
    pkgs.iproute2
    pkgs.util-linux
  ];
  configure-staging = script "configure-staging" [ pkgs.systemd ];
}
