{ config, ... }:
let
  settings = config.fateflix;
in
{
  den.aspects.monitoring.nixos = { config, lib, ... }: {
    imports = [
      ../../hosts/nixflix/notifications.nix
      ../../hosts/nixflix/notifiarr.nix
    ];
    nixflix.notifiarr.enable = lib.mkDefault (
      settings.monitoring.notifiarr.enable && config.nixflixHost.production.enable
    );
  };
}
