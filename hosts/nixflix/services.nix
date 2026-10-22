{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  production = config.nixflixHost.production.enable;
  localServices = builtins.fromJSON (builtins.readFile ./local-services.json);
  bindAddress = if production then "0.0.0.0" else "127.0.0.1";
  secret = name: { _secret = "/var/lib/nixflix-secrets/current/${name}"; };
  arr = name: port: {
    enable = true;
    settings.server.bindaddress = if production then "*" else "127.0.0.1";
    config.apiKey = secret name;
    config.hostConfig = {
      inherit port;
      inherit bindAddress;
      username = null;
    };
    # Preserve restored root folders; do not run automatic deletion/reconciliation.
    mediaDirs = [ ];
    config.rootFolders = lib.mkForce [ ];
  };
  images = builtins.fromJSON (builtins.readFile ./containers.json);
  containers = {
    bazarr = {
      port = 6767;
      internal = 6767;
    };
    bazarr-4k = {
      port = 6777;
      internal = 6767;
    };
    whisparr = {
      port = 6969;
      internal = 6969;
    };
    readarr = {
      port = 8787;
      internal = 8787;
    };
    mylar3 = {
      port = 8090;
      internal = 8090;
    };
    tautulli = {
      port = 8181;
      internal = 8181;
    };
    audiobookshelf = {
      port = 13378;
      internal = 80;
    };
    stash = {
      port = 9999;
      internal = 9999;
    };
  };
in
{
  nixflix = {
    enable = true;
    mediaDir = "/data/media";
    downloadsDir = "/data/usenet";
    serviceDependencies = [ "nixflix-nas-ready.service" ];
    sonarr = arr "sonarr" 8990;
    sonarr-4k = arr "sonarr-4k" 8989;
    radarr = arr "radarr" 7879;
    radarr-4k = arr "radarr-4k" 7878;
    lidarr = arr "lidarr" 8686;
    prowlarr = {
      enable = true;
      settings.server.bindaddress = if production then "*" else "127.0.0.1";
      config.apiKey = secret "prowlarr";
      config.hostConfig = {
        inherit bindAddress;
        username = null;
      };
    };
    usenetClients.sabnzbd = {
      enable = true;
      downloadsDir = "/data/usenet";
      settings.misc = {
        api_key = secret "sabnzbd";
        nzb_key = secret "sabnzbd";
        host = bindAddress;
        port = 8080;
      };
    };
    recyclarr = {
      enable = true;
      cleanupUnmanagedProfiles.enable = false;
      config = {
        sonarr.sonarr.media_naming = lib.mkForce null;
        sonarr.sonarr-4k.media_naming = lib.mkForce null;
        radarr.radarr.media_naming = lib.mkForce null;
        radarr.radarr-4k.media_naming = lib.mkForce null;
      };
    };
    # Leave source download client state intact until explicitly reconciled.
    downloadarr.enable = false;
  };
  environment.etc."nixflix/recyclarr-settings.yml".source =
    (pkgs.formats.yaml { }).generate "recyclarr-settings.yml"
      {
        resource_providers = [
          {
            name = "pinned-guides";
            type = "trash-guides";
            path = "${inputs.trash-guides}";
            replace_default = true;
          }
          {
            name = "pinned-templates";
            type = "config-templates";
            path = "${inputs.recyclarr-templates}";
            replace_default = true;
          }
        ];
      };
  systemd.services.recyclarr = {
    serviceConfig = {
      UMask = "0077";
      StateDirectoryMode = "0700";
    };
    after = lib.mkForce [
      "nixflix-staging-network.service"
      "sonarr.service"
      "sonarr-4k.service"
      "radarr.service"
      "radarr-4k.service"
    ];
    requires = lib.mkForce [
      "nixflix-staging-network.service"
      "sonarr.service"
      "sonarr-4k.service"
      "radarr.service"
      "radarr-4k.service"
    ];
    preStart = lib.mkBefore "install -m 600 /etc/nixflix/recyclarr-settings.yml /var/lib/recyclarr/settings.yml";
  };
  services.plex = {
    enable = true;
    group = "media";
    dataDir = "/var/lib/plex";
  };
  users.users.plex.extraGroups = [
    "video"
    "render"
  ];
  systemd.services.plex.serviceConfig.BindReadOnlyPaths = [ "/data/media:/media" ];
  services.seerr = {
    enable = true;
    port = 5055;
  };
  users.users.seerr = {
    isSystemUser = true;
    group = "media";
  };
  systemd.services.seerr.serviceConfig = {
    DynamicUser = lib.mkForce false;
    User = "seerr";
    Group = "media";
  };
  # Preserve copied providers, paths and queues while managing access and categories.
  systemd.services.sabnzbd.serviceConfig.ExecStartPre = lib.mkForce (
    "+"
    + pkgs.writeShellScript "sabnzbd-migration-prestart" ''
      set -eu
      test -f /var/lib/sabnzbd/sabnzbd.ini
      ${pkgs.python3.withPackages (p: [ p.configobj ])}/bin/python3 - <<'PY'
      from configobj import ConfigObj
      c = ConfigObj('/var/lib/sabnzbd/sabnzbd.ini')
      c['misc']['host'] = '${bindAddress}'
      c['misc']['port'] = '8080'
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
  );
  virtualisation.podman.enable = true;
  virtualisation.oci-containers = {
    backend = "podman";
    containers =
      lib.mapAttrs
        (name: _c: {
          image = images.${name};
          autoStart = false;
          environment = {
            PUID = "1100";
            PGID = "169";
            TZ = "America/Chicago";
          }
          // lib.optionalAttrs (name == "audiobookshelf") { PORT = "13378"; }
          // lib.optionalAttrs (name == "bazarr-4k") { WEBUI_PORTS = "6777/tcp"; }
          // lib.optionalAttrs (name == "stash") {
            STASH_CACHE = "/cache/";
            STASH_STASH = "/data/";
            STASH_GENERATED = "/generated/";
            STASH_METADATA = "/metadata/";
            STASH_CONFIG_FILE = "/root/.stash/config.yml";
          };
          volumes =
            if name == "stash" then
              [
                "/var/lib/nixflix-containers/stash/config:/root/.stash"
                "/var/lib/nixflix-containers/stash/generated:/generated"
                "/var/lib/nixflix-containers/stash/metadata:/metadata"
                "/var/lib/nixflix-containers/stash/cache:/cache"
                "/data/media/porn:/data:ro"
              ]
            else
              [
                "/var/lib/nixflix-containers/${name}:/config"
                ("/data:/data" + lib.optionalString (!production) ":ro")
              ]
              ++ lib.optionals (name == "audiobookshelf") [
                "/var/lib/nixflix-containers/audiobookshelf-metadata:/metadata"
                "/data/media/audiobooks:/audiobooks:ro"
                "/data/media/ebooks:/ebooks:ro"
                ("/data/media/podcasts:/podcasts" + lib.optionalString (!production) ":ro")
              ];
          extraOptions = [
            (if production then "--network=host" else "--network=ns:/run/netns/nixflix-staging")
            "--cgroup-parent=nixflix-staging.slice"
          ];
        })
        (
          lib.filterAttrs (
            name: _:
            lib.elem name [
              "mylar3"
              "stash"
            ]
          ) containers
        );
  };
  users.users.media-container = {
    isSystemUser = true;
    uid = 1100;
    group = "media";
  };
  systemd.tmpfiles.rules = [ "d /var/lib/nixflix-containers 0700 root root -" ];
}
