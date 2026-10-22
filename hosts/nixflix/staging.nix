{
  config,
  lib,
  pkgs,
  ...
}:
let
  production = config.nixflixHost.production.enable;
  native = [
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
  ];
  containers = map (n: "podman-${n}") (
    builtins.attrNames config.virtualisation.oci-containers.containers
  );
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
      serviceConfig.Type = "oneshot";
      script = ''
        set -eu
        if systemctl is-active --quiet data.mount && systemctl is-active --quiet nixflix-nas-ready.service; then
          exit 0
        fi
        systemctl start data.mount
        systemctl start nixflix-nas-ready.service
        systemctl start ${lib.concatMapStringsSep " " (n: "${n}.service") (native ++ containers)}
      '';
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
    bindsTo = [ "data.mount" ];
    unitConfig = {
      RequiresMountsFor = [ "/data" ];
      ConditionPathExists = "/var/lib/nixflix-migration/ready/${name}";
    };
    serviceConfig = {
      Slice = "nixflix-staging.slice";
      ReadWritePaths = lib.mkIf (name == "sabnzbd") (
        lib.mkForce ([ "/var/lib/sabnzbd" ] ++ lib.optional production "/data/usenet")
      );
    }
    // lib.optionalAttrs (lib.elem name native && !production) {
      NetworkNamespacePath = "/run/netns/nixflix-staging";
      ReadOnlyPaths = [ "/data" ];
    };
  })
  // lib.genAttrs automation (_: {
    enable = lib.mkForce false;
  })
  // lib.genAttrs [ "recyclarr" "recyclarr-cleanup-profiles" ] (_: {
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
  systemd.timers.recyclarr.wantedBy = lib.mkForce [ ];
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
  systemd.tmpfiles.rules = [ "d /var/lib/nixflix-migration/ready 0700 root root -" ];
}
