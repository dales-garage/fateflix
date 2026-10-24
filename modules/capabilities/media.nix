{ inputs, ... }: {
  den.aspects.media.nixos.imports = [
    inputs.self.nixosModules.default
    ../_modules/media/services.nix
    ../_modules/media/native-media.nix
    ../_modules/media/homepage.nix
    ../_modules/media/proxy.nix
  ];
}
