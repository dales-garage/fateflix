{ den, ... }: {
  den.aspects.fateflix-base.nixos.imports = [ ../_hosts/nixflix ];
  den.aspects.media-server.includes = [
    den.aspects.fateflix-base
    den.aspects.storage
    den.aspects.secrets
    den.aspects.media
    den.aspects.downloads
    den.aspects.playback
    den.aspects.imports
    den.aspects.monitoring
    den.aspects.freecore
  ];
}
