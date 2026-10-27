{
  config,
  lib,
  pkgs,
  ...
}:
let
  localServices = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json);
  bindAddress = if config.fateflix.host.role == "production" then "0.0.0.0" else "127.0.0.1";
  secret = name: { _secret = "${config.fateflix.secrets.credentialDirectory}/${name}"; };
in
{
  nixflix.usenetClients.sabnzbd = {
    enable = true;
    settings.misc = {
      api_key = secret "sabnzbd";
      nzb_key = secret "sabnzbd";
      host = bindAddress;
      port = 8080;
      download_free = "500G";
      complete_free = "500G";
      fulldisk_autoresume = 0;
    };
  };
  # Preserve copied providers, paths and queues while managing access and categories.
  systemd.services.sabnzbd.serviceConfig.ExecStartPre =
    lib.mkIf config.nixflix.usenetClients.sabnzbd.enable
      (
        lib.mkForce (
          "+"
          + pkgs.writeShellScript "sabnzbd-migration-prestart" ''
            set -eu
            test -f /var/lib/sabnzbd/sabnzbd.ini
            ${pkgs.python3.withPackages (p: [ p.configobj ])}/bin/python3 - <<'PY'
            from configobj import ConfigObj
            c = ConfigObj('/var/lib/sabnzbd/sabnzbd.ini')
            c['misc']['download_dir'] = ${builtins.toJSON config.fateflix.downloads.incompleteDir}
            c['misc']['complete_dir'] = ${builtins.toJSON config.fateflix.downloads.completedDir}
            c['misc']['host'] = '${bindAddress}'
            c['misc']['port'] = '8080'
            c['misc']['download_free'] = '500G'
            c['misc']['complete_free'] = '500G'
            c['misc']['fulldisk_autoresume'] = '0'
            allowed = c['misc'].get('host_whitelist', [])
            if isinstance(allowed, str):
                allowed = [value.strip() for value in allowed.split(',') if value.strip()]
            allowed = [hostname for hostname in allowed if hostname != 'sabnzbd.dalebox.pw']
            for hostname in ('sabnzbd', 'sabnzbd.${localServices.domain}'):
                if hostname not in allowed:
                    allowed.append(hostname)
            c['misc']['host_whitelist'] = allowed
            c['misc']['api_key'] = open('/var/lib/nixflix-secrets/current/sabnzbd').read().strip()
            if 'categories' not in c:
                c['categories'] = {}
            for name in ('sonarr', 'sonarr-4k', 'radarr', 'radarr-4k', 'lidarr'):
                c['categories'][name] = dict(name=name, dir=name, priority='0', pp='3', script='None')
            c.write()
            PY
            chown sabnzbd:media /var/lib/sabnzbd/sabnzbd.ini
            chmod 600 /var/lib/sabnzbd/sabnzbd.ini
          ''
        )
      );
}
