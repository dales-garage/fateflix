{ den, ... }: {
  den.aspects.storage = {
    includes = [
      den.aspects.nixflix-api
      den.aspects.fateflix-context
    ];
    nixos.imports = [ ../../capabilities/storage ];
  };
}
