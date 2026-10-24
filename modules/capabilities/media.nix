{ den, ... }: {
  den.aspects.media = {
    includes = [
      den.aspects.storage
      den.aspects.secrets
      den.aspects.download-policy
    ];
    nixos.imports = [
      ../../capabilities/media/services.nix
      ../../capabilities/media/native-media.nix
      ../../capabilities/media/homepage.nix
      ../../capabilities/media/proxy.nix
    ];
  };
}
