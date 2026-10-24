{
  config,
  lib,
  utils,
  pkgs,
  ...
}:
{
  imports = [
    ./staging.nix
    ./capacity.nix
  ];
  options.fateflix.storage = {
    root = lib.mkOption {
      type = lib.types.strMatching "/.*";
      default = "/data";
    };
    mediaRoot = lib.mkOption {
      type = lib.types.strMatching "/.*";
      default = "${config.fateflix.storage.root}/media";
    };
    downloadsRoot = lib.mkOption {
      type = lib.types.strMatching "/.*";
      default = "${config.fateflix.storage.root}/usenet";
    };
  };
  config = {
    assertions =
      map
        (pair: {
          assertion = pair.actual == pair.expected;
          message = "Configure canonical fateflix.storage paths instead of conflicting upstream aliases";
        })
        [
          {
            actual = config.nixflix.mediaDir;
            expected = config.fateflix.storage.mediaRoot;
          }
          {
            actual = config.nixflix.downloadsDir;
            expected = config.fateflix.storage.downloadsRoot;
          }
          {
            actual = config.nixflix.usenetClients.sabnzbd.downloadsDir;
            expected = config.fateflix.storage.downloadsRoot;
          }
        ];
    nixflix.mediaDir = config.fateflix.storage.mediaRoot;
    nixflix.downloadsDir = config.fateflix.storage.downloadsRoot;
    nixflix.usenetClients.sabnzbd.downloadsDir = config.fateflix.storage.downloadsRoot;
    systemd.tmpfiles.rules = [
      "d /var/lib/nixflix-migration 0700 root root -"
      "d /var/lib/nixflix-secrets 0700 root root -"
    ];
    system.activationScripts.nixflix-mountpoint.text = ''
      if ! ${pkgs.util-linux}/bin/mountpoint -q ${lib.escapeShellArg config.fateflix.storage.root}; then
        ${pkgs.coreutils}/bin/install -d -m 0000 -o root -g root ${lib.escapeShellArg config.fateflix.storage.root}
      fi
    '';
    # No credential values enter the store. The SMB client reads the persistent file.
    systemd.services.nixflix-nas-ready = {
      requires = [
        "${utils.escapeSystemdPath config.fateflix.storage.root}.mount"
        "nixflix-capacity-probe.service"
      ];
      after = [
        "${utils.escapeSystemdPath config.fateflix.storage.root}.mount"
        "nixflix-capacity-probe.service"
      ];
      bindsTo = [ "${utils.escapeSystemdPath config.fateflix.storage.root}.mount" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.python3}/bin/python3 ${../../../scripts/nixflix_ops.py} nas-ready";
        TimeoutStartSec = 10;
      };
    };
  };
}
