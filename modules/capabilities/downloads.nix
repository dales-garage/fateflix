{ den, ... }: {
  flake.nixosModules.download-policy = ../../capabilities/downloads/policy.nix;
  den.aspects.download-policy = {
    includes = [ den.aspects.nixflix-api ];
    nixos.imports = [ ../../capabilities/downloads/policy.nix ];
  };
  den.aspects.downloads = {
    includes = [
      den.aspects.storage
      den.aspects.secrets
      den.aspects.download-policy
    ];
    nixos = {
      imports = [ ../../capabilities/downloads ];
      nixflix.enable = true;
    };
  };
}
