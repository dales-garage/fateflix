{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  local = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json);
  mediaServices = import ../../lib/media-services.nix { inherit lib local; };
  production = config.fateflix.host.role == "production";
  bindAddress = if production then "0.0.0.0" else "127.0.0.1";
  secret = name: { _secret = "${config.fateflix.secrets.credentialDirectory}/${name}"; };
  arr = name: {
    enable = true;
    settings.server.bindaddress = if production then "*" else "127.0.0.1";
    config.apiKey = secret name;
    config.hostConfig = {
      port = mediaServices.ports.${name};
      inherit bindAddress;
      username = null;
    };
    # Preserve restored root folders; do not run automatic deletion/reconciliation.
    mediaDirs = [ ];
    config.rootFolders = lib.mkForce [ ];
    # Keep declared defaults aligned with the Usenet-only restored app state.
    config.delayProfiles = lib.mkForce [
      {
        id = 1;
        enableTorrent = config.fateflix.downloads.torrents.allowed;
        enableUsenet = config.fateflix.downloads.usenet.allowed;
        order = 2147483647;
      }
    ];
  };
  images = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/containers.json);
  # Only these two applications still use containers; retired migration pins
  # remain in containers.json, not a second runtime port catalog here.
  containers = {
    mylar3 = { };
    stash = { };
  };

in
{
  nixflix = {
    enable = true;
    serviceDependencies = [ "nixflix-nas-ready.service" ];
    # This host uses Usenet only, including after future upstream merges.
    sonarr = arr "sonarr";
    sonarr-4k = arr "sonarr-4k";
    radarr = arr "radarr";
    radarr-4k = arr "radarr-4k";
    lidarr = arr "lidarr";
    prowlarr = {
      enable = true;
      settings.server.bindaddress = if production then "*" else "127.0.0.1";
      config.apiKey = secret "prowlarr";
      config.indexerProxies = lib.mkForce [ ];
      config.hostConfig = {
        port = mediaServices.ports.prowlarr;
        inherit bindAddress;
        username = null;
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
    downloadarr = {
      enable = false;
    };
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
  systemd.services.plex.serviceConfig.BindReadOnlyPaths = [ "${config.nixflix.mediaDir}:/media" ];
  services.seerr = {
    enable = true;
    port = mediaServices.ports.seerr;
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
  virtualisation.podman.enable = true;
  virtualisation.oci-containers = {
    backend = "podman";
    containers = lib.mapAttrs (name: _c: {
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
            "${config.nixflix.mediaDir}/porn:/data:ro"
          ]
        else
          [
            "/var/lib/nixflix-containers/${name}:/config"
            ("${config.fateflix.storage.root}:/data" + lib.optionalString (!production) ":ro")
          ]
          ++ lib.optionals (name == "audiobookshelf") [
            "/var/lib/nixflix-containers/audiobookshelf-metadata:/metadata"
            "${config.nixflix.mediaDir}/audiobooks:/audiobooks:ro"
            "${config.nixflix.mediaDir}/ebooks:/ebooks:ro"
            ("${config.nixflix.mediaDir}/podcasts:/podcasts" + lib.optionalString (!production) ":ro")
          ];
      extraOptions = [
        (if production then "--network=host" else "--network=ns:/run/netns/nixflix-staging")
        "--cgroup-parent=nixflix-staging.slice"
      ];
    }) containers;
  };
  users.users.media-container = {
    isSystemUser = true;
    uid = 1100;
    group = "media";
  };
  systemd.tmpfiles.rules = [ "d /var/lib/nixflix-containers 0700 root root -" ];
}
