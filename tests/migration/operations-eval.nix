{
  pkgs,
  host,
  staging,
}:
let
  cfg = host.config;
  roles = [
    cfg
    staging.config
  ];
  customTimeServers =
    (host.extendModules {
      modules = [ { networking.timeServers = pkgs.lib.mkForce [ "time.example.invalid" ]; } ];
    }).config.services.chrony.servers;
  customChronyServers =
    (host.extendModules {
      modules = [ { services.chrony.servers = [ "chrony.example.invalid" ]; } ];
    }).config.services.chrony.servers;
  chronyConfig =
    role:
    let
      command = role.systemd.services.chronyd.serviceConfig.ExecStart;
    in
    # Regex captures lose string context; retain the generated config dependency
    # so a sandboxed check builds the file before parsing it.
    pkgs.lib.strings.addContextFrom command (
      builtins.head (builtins.match ".* -f ([^ ]+)( .*)?" command)
    );
  disabled =
    (host.extendModules {
      modules = [ { fateflix.playback.acceleration = pkgs.lib.mkForce "software"; } ];
    }).config;
  withoutReadarr =
    (host.extendModules { modules = [ { services.readarr.enable = pkgs.lib.mkForce false; } ]; })
    .config;
  sab = cfg.nixflix.usenetClients.sabnzbd.settings.misc;
  # Match actual upstream unit names, not a parallel spelling of those names.
  setupUnits = [
    "sonarr-metadata"
    "sonarr-4k-metadata"
    "radarr-metadata"
    "radarr-4k-metadata"
    "lidarr-metadata"
    "prowlarr-indexer-proxies"
  ];
in
# Xen's host clock is only an initial source: keep one continuously running,
# slew-only guest client in both roles. Exercise the native server override too.
assert builtins.all (
  role:
  role.services.chrony.enable
  && !role.services.ntp.enable
  && !role.services.timesyncd.enable
  && !role.services.chrony.makestep.enable
  && !role.services.chrony.initstepslew.enabled
  && !role.services.chrony.enableRTCTrimming
  && role.services.chrony.extraFlags == [ ]
  && role.services.chrony.extraConfig == "leapsecmode slew\n"
  && role.services.chrony.servers == role.networking.timeServers
  && role.services.chrony.servers != [ ]
  && role.services.chrony.dispatcherScript
  && role.systemd.services.chronyd.enable
  && builtins.elem "multi-user.target" role.systemd.services.chronyd.wantedBy
) roles;
assert customTimeServers == [ "time.example.invalid" ];
assert customChronyServers == [ "chrony.example.invalid" ];
# Restored-state setup is disabled in both appliance roles; production's
# deliberate download-policy reconciliation remains a separate service.
assert builtins.all
  (
    role:
    builtins.all (
      name: !role.systemd.services.${name}.enable && !role.systemd.units."${name}.service".enable
    ) setupUnits
  )
  [
    cfg
    staging.config
  ];
assert cfg.systemd.services.fateflix-download-policy.enable;
assert !(staging.config.systemd.services ? fateflix-download-policy);
assert sab.download_free == "500G" && sab.complete_free == "500G";
assert sab.fulldisk_autoresume == 0;
assert
  !(builtins.elem "readarr"
    (builtins.fromJSON withoutReadarr.environment.etc."nixflix/operations.json".text).services
  );
assert cfg.fateflix.storage.capacity.nas.warning == 1099511627776;
assert cfg.fateflix.storage.capacity.nas.critical == 536870912000;
assert cfg.fateflix.storage.capacity.root.warning == 21474836480;
assert cfg.fateflix.storage.capacity.root.critical == 10737418240;
assert cfg.systemd.timers.notifiarr-connections.timerConfig.OnUnitInactiveSec == "5m";
assert cfg.systemd.services.notifiarr-connections.serviceConfig.TimeoutStartSec == 240;
assert
  cfg.systemd.services.nixflix-health.serviceConfig.TimeoutStartSec
  >= cfg.systemd.services.notifiarr-connections.serviceConfig.TimeoutStartSec
  + cfg.systemd.services.notifiarr-connections.serviceConfig.TimeoutStopSec
  + 120
  + 60;
assert !(cfg.systemd.services.notifiarr-connections.serviceConfig ? Restart);
assert cfg.systemd.services.nixflix-capacity-probe.serviceConfig.TimeoutStartSec == 45;
assert cfg.systemd.services.nixflix-capacity-probe.serviceConfig.ProtectSystem == "strict";
assert cfg.systemd.services.nixflix-nas-ready.serviceConfig.TimeoutStartSec == 10;
assert cfg.systemd.services.nixflix-playback.serviceConfig.TimeoutStartSec == 210;
assert pkgs.lib.hasInfix "enabled" cfg.systemd.services.podman-stash.preStart;
assert pkgs.lib.hasInfix "/usr/bin/ffmpeg /usr/bin/ffprobe disabled"
  disabled.systemd.services.podman-stash.preStart;
assert disabled.services.plex.accelerationDevices == [ ];
assert !(disabled.virtualisation.oci-containers.containers.stash.environment ? LIBVA_DRIVER_NAME);
assert
  !(builtins.elem "--device=/dev/dri:/dev/dri" disabled.virtualisation.oci-containers.containers.stash.extraOptions);
assert
  !(builtins.elem "/nix/store:/nix/store:ro" disabled.virtualisation.oci-containers.containers.stash.volumes);
assert builtins.all
  (
    path:
    builtins.any (
      s: s.check == "http://127.0.0.1:9199/advisory/${path}" && s.expect == "200"
    ) cfg.nixflix.notifiarr.settings.service
  )
  [
    "capacity-warning"
    "capacity-critical"
    "sonarr"
    "readarr"
  ];
pkgs.runCommand "operations-eval" { } ''
  ${pkgs.lib.concatMapStringsSep "\n" (role: ''
    # -p parses and prints only; it never runs a time daemon or sets the clock.
    ${role.services.chrony.package}/bin/chronyd -p -f ${chronyConfig role} > chrony.conf
    grep -Fx 'leapsecmode slew' chrony.conf
    if grep -Ei '^[[:space:]]*(makestep|initstepslew|rtcfile|rtcautotrim)[[:space:]]' chrony.conf; then
      echo 'Unexpected clock-step or RTC-trimming configuration' >&2
      exit 1
    fi
  '') roles}
  ${pkgs.lib.concatMapStringsSep "\n"
    (
      role:
      pkgs.lib.concatMapStringsSep "\n" (name: ''
        test "$(readlink ${role.systemd.units."${name}.service".unit}/${name}.service)" = /dev/null
      '') setupUnits
    )
    [
      cfg
      staging.config
    ]
  }
  touch $out
''
