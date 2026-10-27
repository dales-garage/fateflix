{
  den.aspects.fateflix-context.nixos = { lib, ... }: {
    options.fateflix.host.role = lib.mkOption {
      type = lib.types.enum [
        "production"
        "staging"
      ];
      internal = true;
      description = "Installed operational role; independent of hardware and deployment.";
    };
  };
}
