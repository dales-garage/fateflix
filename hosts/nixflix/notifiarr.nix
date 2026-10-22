{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nixflix.notifiarr;
  ports = (builtins.fromJSON (builtins.readFile ./local-services.json)).services;
  secret = path: format: key: {
    _secret = path;
    inherit format key;
  };
  arrNames =
    lib.filter
      (name: (config.nixflix.${name}.enable or false) || (config.services.${name}.enable or false))
      [
        "sonarr"
        "sonarr-4k"
        "radarr"
        "radarr-4k"
        "lidarr"
        "prowlarr"
        "readarr"
        "whisparr"
      ];
  arrKey = name: secret "/var/lib/${name}/config.xml" "xml" [ "ApiKey" ];
  app = name: {
    inherit name;
    interval = "5m";
    url = "http://127.0.0.1:${toString ports.${name}}";
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
      arr = map (
        name:
        (app name)
        // {
          apiVersion =
            if
              lib.elem name [
                "lidarr"
                "prowlarr"
                "readarr"
              ]
            then
              "v1"
            else
              "v3";
        }
      ) arrNames;
      seerr = {
        url = "http://127.0.0.1:5055";
        api_key = secret "/var/lib/seerr/settings.json" "json" [
          "main"
          "apiKey"
        ];
      };
      bazarr = map (name: {
        inherit name;
        url = "http://127.0.0.1:${toString ports.${name}}";
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
in
{
  config = lib.mkMerge [
    {
      nixflix.notifiarr = {
        enable = config.nixflixHost.production.enable;
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
          sabnzbd = [
            {
              name = "SABnzbd";
              interval = "5m";
              url = "http://127.0.0.1:8080";
              api_key = {
                _secret = "/var/lib/nixflix-secrets/current/sabnzbd";
              };
            }
          ];
          plex = {
            name = "Plex";
            interval = "5m";
            url = "http://127.0.0.1:32400";
            token = secret "/var/lib/plex/Plex Media Server/Preferences.xml" "xml" [ "@PlexOnlineToken" ];
          };
          tautulli = {
            name = "Tautulli";
            interval = "5m";
            url = "http://127.0.0.1:8181";
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
        environment.PYTHONPATH = "${../../modules/notifiarr}";
        serviceConfig = {
          Type = "oneshot";
          StateDirectory = "notifiarr-connections";
          StateDirectoryMode = "0700";
          UMask = "0077";
          ExecStart = "${python}/bin/python3 ${../../scripts/configure-notifiarr.py} ${manifest}";
          Restart = "on-failure";
          RestartSec = "30s";
          ProtectSystem = "strict";
          ProtectHome = true;
          PrivateTmp = true;
        };
        unitConfig.StartLimitBurst = 3;
        unitConfig.StartLimitIntervalSec = 300;
      };
    })
  ];
}
