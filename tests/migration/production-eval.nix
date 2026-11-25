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
assert cfg.fateflix.host.role == "production";
assert pkgs.lib.versionAtLeast cfg.nixflix.prowlarr.package.version "3.1.0.5799";
assert pkgs.lib.versionAtLeast cfg.nixflix.radarr.package.version "7.0.3.10918";
assert cfg.nixflix.radarr-4k.package == cfg.nixflix.radarr.package;
assert pkgs.lib.versionAtLeast cfg.nixflix.lidarr.package.version "3.1.6.5079";
assert builtins.elem (import ../../capabilities/secrets/pass.nix {
  inherit (host) pkgs;
}) cfg.environment.systemPackages;
assert builtins.elem host.pkgs.passage cfg.environment.systemPackages;
assert !(builtins.elem host.pkgs.pass cfg.environment.systemPackages);
assert !cfg.nixflix.notif.pruneUnmanaged;
assert builtins.all
  (
    name:
    let
      script = cfg.systemd.services."${name}-notifications".script;
    in
    pkgs.lib.hasInfix "Nixflix Discord and Matrix" script
    && pkgs.lib.hasInfix ''"tags":"media"'' script
    && !(pkgs.lib.hasInfix "Deleting notification not in config:" script)
    && pkgs.lib.hasInfix "--slurpfile overrides" script
  )
  [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "lidarr"
  ];
assert !cfg.services.flaresolverr.enable;
assert !cfg.services.qbittorrent.enable;
assert cfg.nixflix.usenetClients.sabnzbd.enable;
assert cfg.nixflix.prowlarr.config.indexerProxies == [ ];
assert builtins.all (name: !cfg.nixflix.downloadarr.${name}.enable) [
  "qbittorrent"
  "rtorrent"
  "deluge"
  "transmission"
];
assert builtins.all
  (
    name:
    builtins.all (
      profile: !profile.enableTorrent && profile.enableUsenet
    ) cfg.nixflix.${name}.config.delayProfiles
  )
  [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "lidarr"
  ];
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
assert builtins.all
  (
    name:
    let
      unit = "podman-${name}";
    in
    !(builtins.hasAttr name cfg.virtualisation.oci-containers.containers)
    && cfg.virtualisation.quadlet.containers.${unit}.containerConfig.ContainerName == name
    && cfg.virtualisation.quadlet.containers.${unit}.serviceName == unit
    && cfg.systemd.services.${unit}.wantedBy == [ ]
    && builtins.elem "data.mount" cfg.systemd.services.${unit}.bindsTo
    &&
      builtins.elem "!/var/lib/nixflix-gitops/holds/${unit}"
        cfg.systemd.services.${unit}.unitConfig.ConditionPathExists
  )
  [
    "apprise"
    "mylar3"
    "stash"
  ];
assert builtins.elem "--network=host"
  cfg.virtualisation.quadlet.containers.podman-mylar3.containerConfig.PodmanArgs;
assert
  cfg.virtualisation.quadlet.containers.podman-apprise.containerConfig.PublishPort
  == [ "127.0.0.1:8000:8000" ];
assert builtins.elem "/var/lib/nixflix-secrets/notifications.json"
  cfg.systemd.services.podman-apprise.unitConfig.ConditionPathExists;
assert builtins.all (
  name: !(cfg.systemd.services.${name}.serviceConfig ? NetworkNamespacePath)
) native;
assert builtins.all (name: builtins.elem "data.mount" cfg.systemd.services.${name}.bindsTo) native;
assert builtins.all (
  name:
  cfg.systemd.services.${name}.unitConfig.ConditionPathExists == [
    "/var/lib/nixflix-migration/ready/${name}"
    "!/var/lib/nixflix-gitops/holds/all"
    "!/var/lib/nixflix-gitops/holds/${name}"
  ]
) native;
assert
  builtins.attrNames cfg.fateflix.containers == [
    "apprise"
    "mylar3"
    "stash"
  ];
pkgs.runCommand "production-eval" { } "touch $out"
