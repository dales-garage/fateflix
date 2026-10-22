{
  pkgs,
  host,
  nixosModules,
}:
let
  cfg = host.config;
  baseline = import (pkgs.path + "/nixos/lib/eval-config.nix") {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [ nixosModules ];
  };
  names = [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
  ];
  ports = map (name: cfg.nixflix.${name}.config.hostConfig.port) names;
  apps = map (app: app.name) cfg.nixflix.prowlarr.config.applications;
  categories = map (cat: cat.name) cfg.nixflix.usenetClients.sabnzbd.settings.categories;
in
assert
  ports == [
    8990
    8989
    7879
    7878
  ];
assert baseline.config.nixflix.sonarr.config.hostConfig.port == 8989;
assert baseline.config.nixflix.radarr.config.hostConfig.port == 7878;
assert baseline.config.nixflix.sonarr-anime.config.hostConfig.port == 8990;
assert builtins.all (name: builtins.elem name categories) names;
assert builtins.all (name: builtins.elem name apps) [
  "Sonarr"
  "Sonarr 4k"
  "Radarr"
  "Radarr 4k"
];
assert builtins.all (
  name:
  cfg.systemd.services.${name}.serviceConfig.NetworkNamespacePath == "/run/netns/nixflix-staging"
) names;
assert builtins.all (name: builtins.elem "data.mount" cfg.systemd.services.${name}.bindsTo) names;
assert cfg.services.plex.enable && cfg.services.seerr.enable && !cfg.nixflix.jellyfin.enable;
assert builtins.elem "ro" cfg.fileSystems."/data".options;
assert builtins.hasAttr "sonarr-4k" cfg.services.recyclarr.configuration.sonarr;
assert builtins.hasAttr "radarr-4k" cfg.services.recyclarr.configuration.radarr;
assert builtins.all (name: builtins.hasAttr "${name}-notifications" cfg.systemd.services) names;
assert !cfg.nixflix.notif.pruneUnmanaged;
assert !builtins.hasAttr "notifiarr" cfg.virtualisation.oci-containers.containers;
assert
  cfg.systemd.services.caddy.serviceConfig.NetworkNamespacePath == "/run/netns/nixflix-staging";
assert builtins.hasAttr "http://seeme.dalebox.pw" cfg.services.caddy.virtualHosts;
assert cfg.services.plex.accelerationDevices == [ "/dev/dri/renderD128" ];
pkgs.runCommand "four-instance-eval" { } "touch $out"
