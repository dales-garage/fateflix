{
  den.aspects.secrets.nixos.imports = [ ../_modules/secrets ];
  perSystem = { pkgs, ... }: { apps = import ../_modules/secrets/apps.nix { inherit pkgs; }; };
}
