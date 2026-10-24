{ den, inputs, ... }: {
  den.hosts.x86_64-linux.nixflix-production.hostName = "nixflix";
  den.aspects.nixflix-production = {
    includes = [
      den.aspects.media-server
      den.aspects.deployment
    ];
    nixos.fateflix.host.role = "production";
  };
  flake.nixosConfigurations.nixflix = inputs.self.nixosConfigurations.nixflix-production;
}
