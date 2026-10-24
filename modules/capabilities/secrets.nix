{ den, ... }: {
  den.aspects.secrets = {
    includes = [ den.aspects.fateflix-context ];
    nixos.imports = [ ../../capabilities/secrets ];
  };
  perSystem = { pkgs, ... }: { apps = import ../../capabilities/secrets/apps.nix { inherit pkgs; }; };
}
