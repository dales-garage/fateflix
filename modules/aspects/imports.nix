{ config, ... }:
let
  settings = config.fateflix;
in
{
  den.aspects.imports.nixos = { lib, ... }: {
    imports = [
      ../../hosts/nixflix/imports.nix
      ../../hosts/nixflix/remux.nix
    ];
    nixflixHost.imports.enable = lib.mkDefault settings.imports.av1.enable;
    nixflixHost.remux.enable = lib.mkDefault settings.imports.av1.enable;
  };
}
