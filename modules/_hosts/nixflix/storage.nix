{ config, ... }: {
  fileSystems.${config.fateflix.storage.root} = {
    device = "//10.69.0.10/data";
    fsType = "cifs";
    options = [
      "credentials=/var/lib/nixflix-secrets/current/smb"
      "vers=3.0"
      (if (config.fateflix.host.role == "production") then "rw" else "ro")
      "uid=0"
      "gid=169"
      "file_mode=0664"
      "dir_mode=0775"
      "nofail"
      "_netdev"
      "x-systemd.mount-timeout=30s"
    ];
  };
}
