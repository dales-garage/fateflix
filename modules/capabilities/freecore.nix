{
  den.aspects.freecore.nixos.imports = [
    ../_modules/monitoring/freecore.nix
    ../_hosts/nixflix/freecore.nix
  ];
}
