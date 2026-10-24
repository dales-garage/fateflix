# A stable, credential-free projection for comparing the working host with the
# refactor. Executable source paths can change while runtime identities cannot.
{ host }:
let
  cfg = host.config;
  inherit (host.pkgs) lib;
  field = names: value: lib.filterAttrs (name: _: lib.elem name names) value;
  native = [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "lidarr"
    "prowlarr"
  ];
in
{
  inherit (cfg.networking) hostName firewall;
  inherit (cfg) fileSystems swapDevices;
  identities = lib.mapAttrs (
    _:
    field [
      "uid"
      "group"
      "extraGroups"
      "home"
      "isSystemUser"
      "isNormalUser"
    ]
  ) cfg.users.users;
  groups = lib.mapAttrs (
    _:
    field [
      "gid"
      "members"
    ]
  ) cfg.users.groups;
  services = lib.mapAttrs (_: service: {
    inherit (service) enable wantedBy wants;
    after = builtins.sort builtins.lessThan service.after;
    requires = builtins.sort builtins.lessThan service.requires;
    bindsTo = builtins.sort builtins.lessThan service.bindsTo;
    serviceConfig = field [
      "User"
      "Group"
      "DynamicUser"
      "StateDirectory"
      "StateDirectoryMode"
      "WorkingDirectory"
      "NetworkNamespacePath"
      "ReadWritePaths"
      "ReadOnlyPaths"
      "BindPaths"
      "BindReadOnlyPaths"
      "LoadCredential"
      "Slice"
      "MemoryMax"
      "TimeoutStartSec"
      "Restart"
    ] service.serviceConfig;
    unitConfig = field [ "RequiresMountsFor" "ConditionPathExists" ] service.unitConfig;
  }) cfg.systemd.services;
  timers = lib.mapAttrs (_: timer: { inherit (timer) wantedBy timerConfig; }) cfg.systemd.timers;
  containers = cfg.virtualisation.oci-containers.containers;
  arr = lib.genAttrs native (name: {
    inherit (cfg.nixflix.${name}) dataDir user group;
    version = cfg.nixflix.${name}.package.version;
  });
  versions = lib.genAttrs [
    "plex"
    "bazarr"
    "tautulli"
    "readarr"
    "whisparr"
    "audiobookshelf"
    "sabnzbd"
    "ffmpeg"
    "caddy"
  ] (name: host.pkgs.${name}.version);
  graphics = {
    inherit (cfg.hardware.graphics) enable enable32Bit;
    packages = map toString cfg.hardware.graphics.extraPackages;
    inherit (cfg.boot) extraModprobeConfig;
    firmware = toString cfg.hardware.firmware;
    gpuPassthrough = cfg.fateflix.playback.acceleration == "intel";
  };
  deployment =
    if cfg.services ? comin then
      {
        inherit (cfg.services.comin)
          enable
          hostname
          remotes
          buildTimeout
          buildAttemptsLimit
          buildRetryTimer
          retention
          ;
      }
    else
      { enable = false; };
  runtime = lib.mapAttrs (_: item: item.text) (
    lib.filterAttrs (name: item: lib.hasPrefix "nixflix/" name && item.text != null) cfg.environment.etc
  );
}
