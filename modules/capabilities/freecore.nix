{ den, ... }: {
  den.aspects.freecore = {
    includes = [
      den.aspects.nixflix-api
      den.aspects.fateflix-context
    ];
    nixos.imports = [
      ../../capabilities/freecore
      ../../hosts/nixflix/freecore.nix
    ];
  };
}
