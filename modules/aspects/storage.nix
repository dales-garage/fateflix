{ config, ... }:
let
  settings = config.fateflix;
in
{
  den.aspects.storage.nixos =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    {
      imports = [ ../../hosts/nixflix/staging.nix ];
      nixflix.mediaDir = lib.mkDefault settings.storage.mediaRoot;
      nixflix.downloadsDir = lib.mkDefault settings.storage.downloadsRoot;
      nixflix.usenetClients.sabnzbd.downloadsDir = lib.mkDefault settings.storage.downloadsRoot;
      fileSystems."/data" = {
        device = "//10.69.0.10/data";
        fsType = "cifs";
        options = [
          "credentials=/var/lib/nixflix-secrets/current/smb"
          "vers=3.0"
          (if config.nixflixHost.production.enable then "rw" else "ro")
          "uid=0"
          "gid=169"
          "file_mode=0664"
          "dir_mode=0775"
          "nofail"
          "_netdev"
          "x-systemd.mount-timeout=30s"
        ];
      };
      systemd.tmpfiles.rules = [
        "d /var/lib/nixflix-migration 0700 root root -"
        "d /var/lib/nixflix-secrets 0700 root root -"
      ];
      system.activationScripts.nixflix-mountpoint.text = ''
        if ! ${pkgs.util-linux}/bin/mountpoint -q /data; then
          ${pkgs.coreutils}/bin/install -d -m 0000 -o root -g root /data
        fi
      '';
      # No credential values enter the store. The SMB client reads the persistent file.
      systemd.services.nixflix-nas-ready = {
        requires = [
          "data.mount"
          "nixflix-capacity-probe.service"
        ];
        after = [
          "data.mount"
          "nixflix-capacity-probe.service"
        ];
        bindsTo = [ "data.mount" ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStart = "${pkgs.python3}/bin/python3 ${../../scripts/nixflix_ops.py} nas-ready";
          TimeoutStartSec = 10;
        };
      };
    };
}
