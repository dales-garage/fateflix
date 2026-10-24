{
  config,
  lib,
  utils,
  pkgs,
  ...
}:
let
  production = config.fateflix.host.role == "production";
  native =
    lib.filter
      (
        name:
        (name == "bazarr-4k" && config.users.users ? bazarr-4k)
        || (config.services.${name}.enable or false)
        || (config.nixflix.${name}.enable or false)
        || (name == "sabnzbd" && config.nixflix.usenetClients.sabnzbd.enable)
      )
      [
        "sonarr"
        "sonarr-4k"
        "radarr"
        "radarr-4k"
        "lidarr"
        "prowlarr"
        "sabnzbd"
        "plex"
        "seerr"
        "bazarr"
        "bazarr-4k"
        "tautulli"
        "audiobookshelf"
        "readarr"
        "whisparr"
        "qbittorrent"
        "rtorrent"
        "deluge"
        "transmission"
      ];
  containers = map (n: "podman-${n}") (
    builtins.attrNames config.virtualisation.oci-containers.containers
  );
  operations = "${pkgs.python3}/bin/python3 ${../../scripts/nixflix_ops.py}";
  # Setup jobs may reconcile/delete restored state. They are explicit operations in staging.
  automation =
    lib.concatMap
      (
        n:
        map (suffix: "${n}-${suffix}") [
          "config"
          "rootfolders"
          "mediamanagement"
          "delayprofiles"
          "downloadclients"
        ]
      )
      [
        "sonarr"
        "sonarr-4k"
        "radarr"
        "radarr-4k"
        "lidarr"
        "prowlarr"
      ]
    ++ [
      "prowlarr-applications"
      "prowlarr-indexers"
      "prowlarr-indexerproxies"
      "prowlarr-tags"
      "sabnzbd-categories"
      "lidarr-qualityprofiles"
      "lidarr-metadataprofiles"
    ];
in
{
  systemd.targets.nixflix-staging = {
    description = "Validated, isolated media staging services";
    wantedBy = [ "multi-user.target" ];
    wants = map (name: "${name}.service") (native ++ containers);
    after = [
      "nixflix-staging-network.service"
      "nixflix-nas-ready.service"
    ];
  };
  systemd.services = {
    nixflix-nas-recover = {
      description = "Recover staged media services after NAS connectivity returns";
      path = [ pkgs.systemd ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${operations} recover";
        TimeoutStartSec = 240;
        UMask = "0077";
      };
    };
    nixflix-capacity-probe = {
      description = "Single isolated NAS access and capacity worker";
      after = [ "${utils.escapeSystemdPath config.fateflix.storage.root}.mount" ];
      path = [ pkgs.util-linux ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${operations} probe";
        TimeoutStartSec = 45;
        TimeoutStopSec = 5;
        UMask = "0077";
        ProtectSystem = "strict";
        ReadWritePaths = [ "/var/lib/nixflix-gitops" ];
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };

    nixflix-staging-network = {
      description = "Loopback-only namespace for cloned media identities";
      wantedBy = [ "multi-user.target" ];
      before = map (n: "${n}.service") (native ++ containers);
      path = [ pkgs.iproute2 ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        if [ ! -e /run/netns/nixflix-staging ]; then
          ip netns add nixflix-staging
        fi
        ip -n nixflix-staging link set lo up
      '';
    };
    nixflix-setup-dirs = {
      requires = [ "nixflix-nas-ready.service" ];
      after = [ "nixflix-nas-ready.service" ];
      # Global tmpfiles must never create/chown paths on the production NAS.
      script = lib.mkForce "true";
    };
  }
  // lib.genAttrs (native ++ containers) (name: {
    wantedBy = lib.mkForce [ ];
    requires = [
      "nixflix-nas-ready.service"
      "nixflix-staging-network.service"
    ];
    after = [
      "nixflix-nas-ready.service"
      "nixflix-staging-network.service"
    ];
    bindsTo = [ "${utils.escapeSystemdPath config.fateflix.storage.root}.mount" ];
    unitConfig = {
      RequiresMountsFor = [ config.fateflix.storage.root ];
      ConditionPathExists = [
        "/var/lib/nixflix-migration/ready/${name}"
        "!/var/lib/nixflix-gitops/holds/all"
        "!/var/lib/nixflix-gitops/holds/${name}"
      ];
    };
    serviceConfig = {
      Slice = "nixflix-staging.slice";
      ReadWritePaths = lib.mkIf (name == "sabnzbd") (
        lib.mkForce ([ "/var/lib/sabnzbd" ] ++ lib.optional production config.nixflix.downloadsDir)
      );
    }
    // lib.optionalAttrs (lib.elem name native && !production) {
      NetworkNamespacePath = "/run/netns/nixflix-staging";
      ReadOnlyPaths = [ config.fateflix.storage.root ];
    };
  })
  // lib.genAttrs automation (_: {
    enable = lib.mkForce false;
  })
  //
    lib.genAttrs
      (lib.optionals config.nixflix.recyclarr.enable [
        "recyclarr"
        "recyclarr-cleanup-profiles"
      ])
      (_: {
        wantedBy = lib.mkOverride 40 [ ];
        serviceConfig.NetworkNamespacePath = lib.mkIf (!production) "/run/netns/nixflix-staging";
      });
  systemd.slices.nixflix-staging.sliceConfig = {
    # 16 GiB VM: leave room for the OS and target-side Nix builds.
    MemoryHigh = "10G";
    MemoryMax = "12G";
  };
  # network-online does not guarantee that the NAS itself is reachable. Retry
  # failed boot mounts, then recover only applications previously staged/ready.
  systemd.timers.nixflix-nas-recover = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "1min";
      OnUnitInactiveSec = "1min";
    };
  };
  systemd.timers.nixflix-capacity-probe = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "30s";
      OnUnitInactiveSec = "1m";
    };
  };
  environment.etc."nixflix/operations.json".text = builtins.toJSON {
    services = native ++ containers;
    mountUnit = "${utils.escapeSystemdPath config.fateflix.storage.root}.mount";
    storageRoot = config.fateflix.storage.root;
    nasMode = if production then "rw" else "ro";
    mediaRoot = config.nixflix.mediaDir;
    downloadsRoot = config.nixflix.downloadsDir;
    inherit (config.fateflix.storage.capacity) nas root probeMaxAge;
  };
  systemd.timers.recyclarr = lib.mkIf config.nixflix.recyclarr.enable { wantedBy = lib.mkForce [ ]; };
  # Do not create media/download directories on the read-only production mount.
  systemd.tmpfiles.settings."10-nixflix" = lib.mkForce {
    "/var/lib".d = {
      mode = "0755";
      user = "root";
      group = "root";
    };
  };
  systemd.tmpfiles.settings."10-sabnzbd" = lib.mkForce {
    "/var/lib/sabnzbd".d = {
      mode = "0700";
      user = "sabnzbd";
      group = "media";
    };
  };
  # Per-service credentials are loaded by systemd from root-owned persistent files.
  systemd.tmpfiles.rules = [
    "d /var/lib/nixflix-migration/ready 0700 root root -"
    "d /var/lib/nixflix-gitops 0700 root root -"
    "d /var/lib/nixflix-gitops/holds 0700 root root -"
  ];
}
