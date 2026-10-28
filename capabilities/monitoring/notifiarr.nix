{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nixflix.notifiarr;
  local = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json);
  services = import ../../lib/media-services.nix { inherit lib local; };
  inherit (services) ports;
  secret = path: format: key: {
    _secret = path;
    inherit format key;
  };
  arrNames = services.activeArr config;
  arrKey = name: secret "/var/lib/${name}/config.xml" "xml" [ "ApiKey" ];
  app = name: {
    inherit name;
    interval = "5m";
    url = services.origin name;
    api_key = arrKey name;
  };
  bazarrNames = [
    "bazarr"
    "bazarr-4k"
  ];
  manifest = pkgs.writeText "notifiarr-connections.json" (
    builtins.toJSON {
      apiKey = {
        _secret = cfg.apiKeyFile;
      };
      arr = map (name: (app name) // { apiVersion = services.catalog.${name}.apiVersion; }) arrNames;
      seerr = {
        url = services.origin "seerr";
        api_key = secret "/var/lib/seerr/settings.json" "json" [
          "main"
          "apiKey"
        ];
      };
      bazarr = map (name: {
        inherit name;
        url = services.origin name;
        api_key = secret "/var/lib/${name}/config/config.yaml" "yaml" [
          "auth"
          "apikey"
        ];
      }) bazarrNames;
      plex = cfg.settings.plex;
      plexWebhook = "http://127.0.0.1:${toString cfg.port}/plex";
    }
  );
  python = pkgs.python3.withPackages (p: [ p.pyyaml ]);
  connectionService = mode: {
    environment.PYTHONPATH = "${../../integrations/nixflix/compatibility/notifiarr}";
    serviceConfig = {
      Type = "oneshot";
      StateDirectory = "notifiarr-connections";
      StateDirectoryMode = "0700";
      UMask = "0077";
      ExecStart = "${python}/bin/python3 ${../../scripts/configure-notifiarr.py} ${manifest} ${mode}";
      TimeoutStartSec = 240;
      TimeoutStopSec = 5;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
    };
  };
in
{
  imports = [ ./notifications.nix ];
  config = lib.mkIf (config.fateflix.host.role == "production") (
    lib.mkMerge [
      {
        nixflix.notifiarr = {
          apiKeyFile = "/var/lib/nixflix-secrets/notifiarr-api-key";
          listenAddress = "0.0.0.0";
          settings = {
            auto_update = "off";
            quiet = false;
            debug = false;
            log_file = "/var/lib/notifiarr/app.log";
            http_log = "/var/lib/notifiarr/http.log";
            sonarr = map app (lib.filter (lib.hasPrefix "sonarr") arrNames);
            radarr = map app (lib.filter (lib.hasPrefix "radarr") arrNames);
            lidarr = map app (lib.filter (name: name == "lidarr") arrNames);
            prowlarr = map app (lib.filter (name: name == "prowlarr") arrNames);
            readarr = map app (lib.filter (name: name == "readarr") arrNames);
            sabnzbd = lib.optional config.nixflix.usenetClients.sabnzbd.enable {
              name = "SABnzbd";
              interval = "5m";
              url = services.origin "sabnzbd";
              api_key = {
                _secret = "/var/lib/nixflix-secrets/current/sabnzbd";
              };
            };
            plex = {
              name = "Plex";
              interval = "5m";
              url = services.origin "plex";
              token = secret "/var/lib/plex/Plex Media Server/Preferences.xml" "xml" [ "@PlexOnlineToken" ];
            };
            tautulli = {
              name = "Tautulli";
              interval = "5m";
              url = services.origin "tautulli";
              api_key = secret "/var/lib/tautulli/config.ini" "ini" [
                "General"
                "api_key"
              ];
            };
            # These applications have no direct client connector; track availability.
            service =
              map
                (name: {
                  inherit name;
                  type = "tcp";
                  check = "127.0.0.1:${toString ports.${name}}";
                  interval = "5m";
                  timeout = "10s";
                })
                [
                  "seerr"
                  "bazarr"
                  "bazarr-4k"
                  "whisparr"
                  "audiobookshelf"
                  "mylar3"
                  "stash"
                  "homepage"
                ];
          };
        };
      }
      (lib.mkIf cfg.enable {
        networking.firewall.extraCommands =
          lib.concatMapStringsSep "\n"
            (
              network: "iptables -A nixos-fw -s ${network} -p tcp --dport ${toString cfg.port} -j nixos-fw-accept"
            )
            [
              "10.69.0.0/24"
              "10.42.0.0/24"
            ];
        systemd.services.notifiarr.after = map (name: "${name}.service") (
          arrNames
          ++ [
            "plex"
            "tautulli"
          ]
        );
        systemd.services.notifiarr-connections = {
          description = "Reconcile Notifiarr application notifications";
          wantedBy = [ "multi-user.target" ];
          wants = map (name: "${name}.service") (
            arrNames
            ++ bazarrNames
            ++ [
              "notifiarr"
              "seerr"
              "plex"
            ]
          );
          after = map (name: "${name}.service") (
            arrNames
            ++ bazarrNames
            ++ [
              "notifiarr"
              "seerr"
              "plex"
            ]
          );
        }
        // connectionService "--local-only";
        systemd.services.notifiarr-plex-webhooks = {
          description = "Reconcile Plex account webhooks independently of local media readiness";
          wants = [ "network-online.target" ];
          after = [ "network-online.target" ];
        }
        // connectionService "--plex-webhooks-only";
        systemd.timers.notifiarr-plex-webhooks = {
          wantedBy = [ "timers.target" ];
          timerConfig = {
            # Keep cloud availability out of boot and activation transactions.
            OnActiveSec = "5m";
            OnUnitInactiveSec = "5m";
          };
        };
        systemd.timers.notifiarr-connections = {
          wantedBy = [ "timers.target" ];
          timerConfig = {
            OnBootSec = "3m";
            OnUnitInactiveSec = "5m";
          };
        };
      })
    ]
  );
}
