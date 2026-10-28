{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = {
    torrents = config.fateflix.downloads.torrents.allowed;
    usenet = config.fateflix.downloads.usenet.allowed;
  };
  local = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json);
  services = import ../../lib/media-services.nix { inherit lib local; };
  names = services.activeArr config;
  manifest = pkgs.writeText "fateflix-download-policy.json" (
    builtins.toJSON {
      inherit (cfg) torrents usenet;
      apps = map (name: {
        inherit name;
        url = "${services.origin name}/api/${services.catalog.${name}.apiVersion}";
      }) names;
    }
  );
in
{
  imports = [ ./sabnzbd.nix ];
  options.fateflix.downloads = {
    incompleteDir = lib.mkOption {
      type = lib.types.strMatching "/.*";
      default = "${config.fateflix.storage.downloadsRoot}/incomplete";
    };
    completedDir = lib.mkOption {
      type = lib.types.strMatching "/.*";
      default = "${config.fateflix.storage.downloadsRoot}/complete";
    };
  };
  config = {
    nixflix.usenetClients.sabnzbd.settings.misc = {
      download_dir = config.fateflix.downloads.incompleteDir;
      complete_dir = config.fateflix.downloads.completedDir;
    };
    assertions =
      map
        (pair: {
          assertion = pair.actual == pair.expected;
          message = "Configure canonical fateflix.downloads paths instead of conflicting SABnzbd aliases";
        })
        [
          {
            actual = config.nixflix.usenetClients.sabnzbd.settings.misc.download_dir;
            expected = config.fateflix.downloads.incompleteDir;
          }
          {
            actual = config.nixflix.usenetClients.sabnzbd.settings.misc.complete_dir;
            expected = config.fateflix.downloads.completedDir;
          }
        ];
    systemd.services.fateflix-download-policy =
      lib.mkIf ((config.fateflix.host.role == "production") && (!cfg.torrents || !cfg.usenet))
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
      lib.mkIf ((config.fateflix.host.role == "production") && (!cfg.torrents || !cfg.usenet))
        {
          wantedBy = [ "timers.target" ];
          timerConfig = {
            OnBootSec = "2m";
            OnUnitInactiveSec = "5m";
          };
        };
  };
}
