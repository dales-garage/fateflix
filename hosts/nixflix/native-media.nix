{ config, pkgs, ... }: {
  services.bazarr = {
    enable = true;
    group = "media";
    dataDir = "/var/lib/bazarr";
  };
  # NixOS's Bazarr module is single-instance; use its pinned package for 4K too.
  users.users.bazarr-4k = {
    isSystemUser = true;
    group = "media";
  };
  systemd.services.bazarr-4k = {
    description = "Bazarr subtitles for the 4K Arr pair";
    after = [ "network.target" ];
    serviceConfig = {
      User = "bazarr-4k";
      Group = "media";
      ExecStart = "${config.services.bazarr.package}/bin/bazarr --config /var/lib/bazarr-4k --port 6777 --no-update True";
      Restart = "on-failure";
      KillSignal = "SIGINT";
      SuccessExitStatus = "0 156";
    };
  };
  services.tautulli = {
    enable = true;
    user = "tautulli";
    group = "media";
    dataDir = "/var/lib/tautulli";
    configFile = "/var/lib/tautulli/config.ini";
  };
  users.users.tautulli = {
    isSystemUser = true;
    group = "media";
  };
  services.audiobookshelf = {
    enable = true;
    group = "media";
    host = if config.nixflixHost.production.enable then "0.0.0.0" else "127.0.0.1";
    port = 13378;
  };
  systemd.services.audiobookshelf.serviceConfig = {
    BindReadOnlyPaths = [
      "/data/media/audiobooks:/audiobooks"
      "/data/media/ebooks:/ebooks"
    ];
    BindPaths = [
      "/data/media/podcasts:/podcasts"
      "/var/lib/audiobookshelf/metadata:/metadata"
      "/var/lib/audiobookshelf/config:/config"
    ];
  };
  services.readarr = {
    enable = true;
    group = "media";
    dataDir = "/var/lib/readarr";
  };
  services.whisparr = {
    enable = true;
    package = pkgs.callPackage ../../pkgs/whisparr { };
    group = "media";
    dataDir = "/var/lib/whisparr";
  };
}
