{ config, ... }:
let
  settings = config.fateflix;
in
{
  flake.nixosModules.download-policy = ../_support/download-policy.nix;
  den.aspects.downloads.nixos =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      cfg = config.fateflixPolicy;
      names =
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
      local = (builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json)).services;
      manifest = pkgs.writeText "fateflix-download-policy.json" (
        builtins.toJSON {
          inherit (cfg) torrents usenet;
          apps = map (name: {
            inherit name;
            url = "http://127.0.0.1:${toString local.${name}}/api/${
              if
                lib.elem name [
                  "lidarr"
                  "prowlarr"
                  "readarr"
                ]
              then
                "v1"
              else
                "v3"
            }";
          }) names;
        }
      );
    in
    {
      imports = [ ../_support/download-policy.nix ];
      systemd.services.fateflix-download-policy =
        lib.mkIf (config.nixflixHost.production.enable && (!cfg.torrents || !cfg.usenet))
          {
            description = "Enforce download protocol policy on restored applications";
            wantedBy = [ "multi-user.target" ];
            after = map (name: "${name}.service") names;
            unitConfig.ConditionPathExists = [ "!/var/lib/nixflix-gitops/holds/all" ];
            serviceConfig = {
              Type = "oneshot";
              ExecStart = "${pkgs.python3}/bin/python3 ${../../scripts/download-policy.py} ${manifest}";
              TimeoutStartSec = 240;
              UMask = "0077";
              ProtectSystem = "strict";
              ProtectHome = true;
              PrivateTmp = true;
              NoNewPrivileges = true;
            };
          };
      systemd.timers.fateflix-download-policy =
        lib.mkIf (config.nixflixHost.production.enable && (!cfg.torrents || !cfg.usenet))
          {
            wantedBy = [ "timers.target" ];
            timerConfig = {
              OnBootSec = "2m";
              OnUnitInactiveSec = "5m";
            };
          };
      fateflixPolicy = {
        torrents = lib.mkDefault settings.downloads.torrents.enable;
        usenet = lib.mkDefault settings.downloads.usenet.enable;
      };
    };
}
