{ inputs, pkgs }:
let
  inherit (pkgs) lib;
  local = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json);
  services = import ../../lib/media-services.nix { inherit lib local; };
  cfg = inputs.self.nixosConfigurations.nixflix-production.config;
  staging = inputs.self.nixosConfigurations.nixflix-staging.config;
  manifest = builtins.fromJSON cfg.environment.etc."nixflix/gitops-services.json".text;
  normalize =
    value:
    (lib.evalModules {
      modules = [
        { options.service = lib.mkOption { type = services.serviceType; }; }
        { service = value; }
      ];
    }).config.service;
  fails = value: !(builtins.tryEval (builtins.deepSeq (normalize value) true)).success;
  mismatchedAlias = import ../../lib/media-services.nix {
    inherit lib;
    local = local // {
      services = local.services // {
        seeme = 5056;
      };
    };
  };
  disabled = {
    nixflix.usenetClients.sabnzbd.enable = false;
  };
in
assert services.ports == local.services;
assert manifest.services == local.services;
assert manifest.serviceCatalog == services.health cfg;
assert builtins.attrNames manifest.serviceCatalog == builtins.attrNames local.services;
assert
  services.activeArr cfg == [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "lidarr"
    "prowlarr"
    "readarr"
    "whisparr"
  ];
assert services.activeArr staging == services.activeArr cfg;
assert services.catalog.lidarr.apiVersion == "v1";
assert services.catalog.prowlarr.apiVersion == "v1";
assert services.catalog.readarr.apiVersion == "v1";
assert services.catalog.whisparr.apiVersion == "v3";
assert services.catalog.homepage.unit == "homepage-dashboard";
assert services.catalog.mylar3.unit == "podman-mylar3";
assert services.catalog.stash.unit == "podman-stash";
assert services.catalog.seeme.aliasOf == "seerr";
assert services.catalog.seeme.port == services.catalog.seerr.port;
assert !(builtins.tryEval (builtins.deepSeq mismatchedAlias.catalog true)).success;
assert services.catalog.plex.dashboardPath == "/web/";
assert services.catalog.plex.healthPath == "/";
assert !(services.proxyPorts disabled ? sabnzbd);
assert !(services.health disabled ? sabnzbd);
assert !(builtins.elem "sabnzbd" (services.activeWidgets disabled));
assert builtins.all (name: cfg.nixflix.${name}.config.hostConfig.port == services.ports.${name}) [
  "sonarr"
  "sonarr-4k"
  "radarr"
  "radarr-4k"
  "lidarr"
  "prowlarr"
];
assert cfg.services.seerr.port == services.ports.seerr;
assert cfg.services.bazarr.listenPort == services.ports.bazarr;
assert cfg.services.tautulli.port == services.ports.tautulli;
assert cfg.services.audiobookshelf.port == services.ports.audiobookshelf;
assert cfg.nixflix.usenetClients.sabnzbd.settings.misc.port == services.ports.sabnzbd;
assert cfg.nixflix.homepage.listenPort == services.ports.homepage;
assert fails { port = 0; };
assert fails { port = 65536; };
assert fails { port = "8080"; };
assert fails {
  port = 8080;
  apiVersion = "v2";
};
assert fails {
  port = 8080;
  _secret = "/private/key";
};
assert fails {
  port = 8080;
  healthPath = "not-an-absolute-path";
};
pkgs.runCommand "service-catalog-eval" { } "touch $out"
