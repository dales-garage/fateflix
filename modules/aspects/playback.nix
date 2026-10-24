{ config, ... }:
let
  settings = config.fateflix;
in
{
  den.aspects.playback.nixos = { pkgs, lib, ... }: {
    imports = [ ../../hosts/nixflix/gpu.nix ];
    nixflixHost.gpuPassthrough.enable = lib.mkDefault settings.playback.gpu.enable;
    hardware.graphics = {
      enable = settings.playback.gpu.enable;
      extraPackages = [
        pkgs.intel-media-driver
        pkgs.intel-vaapi-driver
      ];
    };
  };
}
