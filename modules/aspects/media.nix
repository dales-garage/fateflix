{ inputs, ... }: {
  den.aspects.media.nixos.imports = [
    inputs.self.nixosModules.default
    ../../hosts/nixflix/services.nix
    ../../hosts/nixflix/native-media.nix
    ../../hosts/nixflix/homepage.nix
    ../../hosts/nixflix/proxy.nix
  ];
  den.aspects.fateflix-base.nixos.imports = [
    ../../hosts/nixflix
    ../../hosts/nixflix/production.nix
  ];
}
