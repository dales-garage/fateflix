{
  flake.nixosModules.download-policy = ../_modules/downloads/policy.nix;
  den.aspects.downloads.nixos.imports = [ ../_modules/downloads ];
}
