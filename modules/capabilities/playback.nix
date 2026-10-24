{ den, ... }: {
  den.aspects.playback = {
    includes = [ den.aspects.media ];
    nixos.imports = [ ../../capabilities/playback ];
  };
}
