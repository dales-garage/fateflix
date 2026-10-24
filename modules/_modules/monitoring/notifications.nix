{
  config,
  lib,
  pkgs,
  ...
}:
let
  production = config.fateflix.host.role == "production";
  arr = [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "lidarr"
  ];
  credential = "/var/lib/nixflix-secrets/notifications.json";
in
{
  config = lib.mkMerge [
    {
      users.groups.nixflix-apprise.gid = 1101;
      users.users.nixflix-apprise = {
        isSystemUser = true;
        uid = 1101;
        group = "nixflix-apprise";
      };
    }
    (lib.mkIf production {
      # No public listener: callers share the staging namespace. Production must
      # preserve loopback-only access to this API when networking is changed.
      virtualisation.oci-containers.containers.apprise = {
        image = "docker.io/caronc/apprise@sha256:c5ea17408c10fd84c8fdb05a421114a1a677b16343c274bf9b1a55701b530829";
        autoStart = false;
        environment = {
          PUID = "1101";
          PGID = "1101";
          HTTP_PORT = "8000";
          APPRISE_STATEFUL_MODE = "simple";
          APPRISE_CONFIG_LOCK = "yes";
          APPRISE_WORKER_COUNT = "1";
          APPRISE_API_ONLY = "yes";
          APPRISE_ADMIN = "no";
          APPRISE_ATTACH_SIZE = "0";
          APPRISE_STORAGE_DIR = "/storage";
          APPRISE_ALLOW_SERVICES = "discord,matrix,matrixs";
        };
        volumes = [
          "/run/nixflix-apprise:/config:ro"
          "/var/lib/nixflix-apprise:/storage"
        ];
        ports = lib.optional production "127.0.0.1:8000:8000";
        extraOptions = lib.optional (!production) "--network=ns:/run/netns/nixflix-staging" ++ [
          "--cgroup-parent=nixflix-staging.slice"
        ];
      };
      nixflix.notif = {
        pruneUnmanaged = false;
        extraNotifications = [
          {
            enable = true;
            name = "Nixflix Discord and Matrix";
            implementationName = "Apprise";
            services = arr;
            dependencies = [ "podman-apprise.service" ];
            serverUrl = "http://127.0.0.1:8000";
            configurationKey = "media";
            tags = "media";
            triggers = {
              sonarr = [
                "onDownload"
                "onHealthIssue"
                "onHealthRestored"
                "onManualInteractionRequired"
              ];
              radarr = [
                "onDownload"
                "onHealthIssue"
                "onHealthRestored"
                "onManualInteractionRequired"
              ];
              lidarr = [
                "onReleaseImport"
                "onHealthIssue"
                "onHealthRestored"
              ];
            };
          }
        ];
      };
      # Configuration is a deliberate migration operation, never implicit deletion
      # or outbound delivery from a clone. Missing credentials leave it inactive.
      systemd.services = lib.mkMerge [
        {
          seerr.preStart = lib.mkIf (!config.nixflix.notifiarr.enable) ''
            ${pkgs.python3}/bin/python3 ${../../../scripts/configure-seerr-notifications.py} /var/lib/seerr/settings.json --application-url https://seeme.dalebox.pw
          '';
          podman-apprise = {
            unitConfig.ConditionPathExists = [ credential ];
            preStart = lib.mkBefore ''
              ${pkgs.coreutils}/bin/install -d -m 0700 -o 1101 -g 1101 /run/nixflix-apprise /var/lib/nixflix-apprise
              ${pkgs.coreutils}/bin/install -m 0400 -o 1101 -g 1101 ${credential} /run/nixflix-apprise/media.yml
            '';
          };
        }
        (lib.genAttrs (map (name: "${name}-notifications") arr) (
          unit:
          let
            name = lib.removeSuffix "-notifications" unit;
          in
          {
            wantedBy = lib.mkForce [ ];
            requires = lib.mkForce [
              "${name}.service"
              "podman-apprise.service"
            ];
            after = lib.mkForce [
              "${name}.service"
              "podman-apprise.service"
            ];
            unitConfig.ConditionPathExists = [
              credential
              "/var/lib/nixflix-migration/ready/podman-apprise"
            ];
            serviceConfig = {
              NetworkNamespacePath = lib.mkIf (!production) "/run/netns/nixflix-staging";
              UMask = "0077";
            };
          }
        ))
      ];
    })
  ];
}
