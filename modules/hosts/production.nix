{ den, ... }: {
  den.hosts.x86_64-linux.nixflix-production.hostName = "nixflix";
  den.aspects.nixflix-production = {
    includes = [
      den.aspects.fateflix-base
      den.aspects.media
      den.aspects.downloads
      den.aspects.playback
      den.aspects.storage
      den.aspects.imports
      den.aspects.monitoring
      den.aspects.secrets
      den.aspects.deployment
    ];
    nixos.nixflixHost.production.enable = true;
  };
}
