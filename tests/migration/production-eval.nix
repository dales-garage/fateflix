{ pkgs, host }:
let
  cfg = host.config;
  localServices = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json);
  native = [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "prowlarr"
    "sabnzbd"
    "plex"
    "seerr"
    "lidarr"
    "bazarr"
    "bazarr-4k"
    "tautulli"
    "audiobookshelf"
    "readarr"
    "whisparr"
  ];
in
assert cfg.nixflixHost.production.enable;
assert builtins.elem "rw" cfg.fileSystems."/data".options;
assert cfg.networking.firewall.allowedTCPPorts == [ 22 ];
assert pkgs.lib.hasInfix "iptables -A nixos-fw -p tcp --dport 32400 -j nixos-fw-accept"
  cfg.networking.firewall.extraCommands;
assert builtins.all (
  name:
  pkgs.lib.hasInfix "reverse_proxy http://127.0.0.1:${
    toString localServices.services.${name}
  }" cfg.services.caddy.virtualHosts."http://${name}.${localServices.domain}".extraConfig
) (builtins.attrNames localServices.services);
assert !(builtins.elem "plex.vm.internal" (cfg.networking.hosts."127.0.0.1" or [ ]));
assert builtins.all
  (
    name:
    !(cfg.services.caddy.virtualHosts ? "http://${name}.dalebox.pw")
    && !(builtins.elem name localServices.publicServices)
  )
  [
    "stash"
    "whisparr"
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "sabnzbd"
    "bazarr"
    "bazarr-4k"
  ];
assert pkgs.lib.hasInfix "-s 10.42.0.0/24 -p tcp --dport 32400 -j nixos-fw-accept"
  cfg.networking.firewall.extraCommands;
assert cfg.virtualisation.oci-containers.backend == "podman";
assert cfg.virtualisation.oci-containers.containers.apprise.ports == [ "127.0.0.1:8000:8000" ];
assert builtins.all (
  name: !(cfg.systemd.services.${name}.serviceConfig ? NetworkNamespacePath)
) native;
assert builtins.all (name: builtins.elem "data.mount" cfg.systemd.services.${name}.bindsTo) native;
assert builtins.all (
  name:
  cfg.systemd.services.${name}.unitConfig.ConditionPathExists
  == "/var/lib/nixflix-migration/ready/${name}"
) native;
assert
  builtins.attrNames cfg.virtualisation.oci-containers.containers == [
    "apprise"
    "mylar3"
    "stash"
  ];
pkgs.runCommand "production-eval" { } "touch $out"
