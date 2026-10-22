{
  pkgs,
  host,
  staging,
  nixosModules,
}:
let
  inherit (pkgs) lib;
  cfg = host.config;
  dashboard = cfg.services.homepage-dashboard;
  service = cfg.systemd.services.homepage-dashboard;
  cards = lib.concatMap (group: lib.concatLists (lib.attrValues group)) dashboard.services;
  entries = lib.concatMap lib.attrValues cards;
  manifest = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json);
  expected = builtins.removeAttrs manifest.services [
    "homepage"
    "seeme"
  ];
  linksOnly =
    (host.extendModules {
      modules = [
        {
          nixflixHost.homepage = {
            apiWidgets = false;
            useInternalNames = false;
            showAdultServices = false;
          };
        }
      ];
    }).config;
  localCards = lib.concatMap (
    group: lib.concatLists (lib.attrValues group)
  ) linksOnly.services.homepage-dashboard.services;
  standalone =
    (import (pkgs.path + "/nixos/lib/eval-config.nix") {
      system = pkgs.stdenv.hostPlatform.system;
      modules = [
        nixosModules
        {
          nixflix = {
            enable = true;
            caddy = {
              enable = true;
              domain = "example.internal";
              tls.enable = false;
            };
            homepage = {
              enable = true;
              reverseProxy.expose = true;
              apiKeyFiles.SONARR = "/run/secrets/test-sonarr";
            };
          };
        }
      ];
    }).config;
in
assert dashboard.enable && !staging.config.services.homepage-dashboard.enable;
assert dashboard.listenPort == manifest.services.homepage;
assert builtins.length cards == builtins.length (builtins.attrNames expected);
assert builtins.all (
  name:
  builtins.any (
    entry: entry.href == "https://${name}.vm.internal/" + (if name == "plex" then "web/" else "")
  ) entries
) (builtins.attrNames expected);
assert builtins.length (builtins.filter (entry: entry ? widget) entries) == 7;
assert builtins.all (entry: lib.hasPrefix "http://127.0.0.1:" entry.siteMonitor) entries;
assert service.environment.HOMEPAGE_FILE_SONARR_4K == "%d/SONARR_4K";
assert builtins.elem "SONARR_4K:/var/lib/nixflix-secrets/current/sonarr-4k"
  service.serviceConfig.LoadCredential;
assert service.serviceConfig.DynamicUser;
assert !dashboard.openFirewall && cfg.networking.firewall.allowedTCPPorts == [ 22 ];
assert builtins.all
  (
    network:
    lib.hasInfix "-s ${network} -p tcp --dport 8082 -j nixos-fw-accept" cfg.networking.firewall.extraCommands
  )
  [
    "10.69.0.0/24"
    "10.42.0.0/24"
  ];
assert lib.hasInfix "reverse_proxy http://127.0.0.1:8082"
  cfg.services.caddy.virtualHosts."http://homepage.vm.internal".extraConfig;
assert !(cfg.services.caddy.virtualHosts ? "http://homepage.dalebox.pw");
assert !(builtins.elem "homepage" manifest.publicServices);
assert !(lib.hasInfix "*" dashboard.allowedHosts);
assert linksOnly.systemd.services.homepage-dashboard.serviceConfig.LoadCredential == [ ];
assert builtins.length localCards == 15;
assert builtins.all (
  card:
  builtins.all (entry: !(entry ? widget) && lib.hasPrefix "http://10.69.0.18:" entry.href) (
    lib.attrValues card
  )
) localCards;
assert standalone.systemd.services.homepage-dashboard.environment.HOSTNAME == "127.0.0.1";
assert
  standalone.systemd.services.homepage-dashboard.environment.HOMEPAGE_FILE_SONARR == "%d/SONARR";
assert lib.hasInfix "reverse_proxy http://127.0.0.1:8082"
  standalone.services.caddy.virtualHosts."http://homepage.example.internal".extraConfig;
assert lib.hasInfix "homepage.example.internal" standalone.services.homepage-dashboard.allowedHosts;
pkgs.runCommand "homepage-eval" { } "touch $out"
