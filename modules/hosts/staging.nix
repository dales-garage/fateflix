{ den, inputs, ... }: {
  den.hosts.x86_64-linux.nixflix-staging.hostName = "nixflix";
  den.aspects.nixflix-staging = {
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
    nixos.nixflixHost.production.enable = false;
  };
  # Preserve the historical default output, which is production on this host.
  flake.nixosConfigurations.nixflix = inputs.self.nixosConfigurations.nixflix-production;
}
