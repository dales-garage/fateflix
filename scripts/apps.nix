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
  provision =
    name: profile: scriptName:
    app name [ pkgs.secretspec pkgs.pass pkgs.gnupg ] ''
      if [[ "''${1:-}" == "--help" ]]; then
        echo "Run as marty on nixflix. Resolves the ${profile} pass profile and atomically installs root-owned credentials."
        exit 0
      fi
      secretspec --file ${self}/secretspec.toml run --profile ${profile} --provider pass -- \
        ${python}/bin/python3 ${self}/scripts/${scriptName}.py emit | \
        /run/wrappers/bin/sudo -n ${python}/bin/python3 ${self}/scripts/${scriptName}.py install
    '';
in
{
  deploy = script "deploy" [
    pkgs.jujutsu
    pkgs.openssh
  ];
  snapshot = script "snapshot" [ ];
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
  provision = provision "provision" "default" "provision-secrets";
  provision-notifiarr = app "provision-notifiarr" [ pkgs.secretspec pkgs.pass pkgs.gnupg ] ''
    secretspec --file ${self}/secretspec-notifiarr.toml run --profile notifiarr --provider pass -- \
      ${python}/bin/python3 ${self}/scripts/provision-notifiarr.py emit | \
      /run/wrappers/bin/sudo -n ${python}/bin/python3 ${self}/scripts/provision-notifiarr.py install
  '';
  provision-notifications =
    provision "provision-notifications" "notifications"
      "provision-notifications";
}
