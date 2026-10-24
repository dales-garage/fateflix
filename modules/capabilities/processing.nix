{ den, ... }: {
  den.aspects.processing = {
    includes = [ den.aspects.media ];
    nixos.imports = [ ../../capabilities/processing ];
  };
}
