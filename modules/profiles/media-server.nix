{ den, ... }: {
  den.aspects.fateflix-base = {
    includes = [ den.aspects.storage ];
    nixos.imports = [ ../../hosts/nixflix ];
  };
  den.aspects.media-server = {
    includes = [
      den.aspects.fateflix-base
      den.aspects.downloads
      den.aspects.playback
      den.aspects.processing
      den.aspects.monitoring
      den.aspects.freecore
    ];
    # These restored application paths belong to this complete host profile,
    # not the reusable machine base or the downloads capability's defaults.
    nixos = { config, lib, ... }: {
      fateflix.downloads = {
        incompleteDir = lib.mkDefault "${config.fateflix.storage.downloadsRoot}/intermediate";
        completedDir = lib.mkDefault "${config.fateflix.storage.downloadsRoot}/";
      };
    };
  };
}
