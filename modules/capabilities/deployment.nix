{ den, ... }: {
  den.aspects.deployment = {
    includes = [ den.aspects.playback ];
    nixos.imports = [ ../../capabilities/deployment/gitops.nix ];
  };
}
