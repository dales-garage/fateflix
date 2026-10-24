{
  config,
  lib,
  pkgs,
  ...
}:
{
  imports = [ ./gpu.nix ];
  options.fateflix.playback.acceleration = lib.mkOption {
    type = lib.types.enum [
      "intel"
      "software"
    ];
    default = "intel";
    description = "Playback acceleration mode.";
  };
  config.hardware.graphics = {
    enable = config.fateflix.playback.acceleration == "intel";
    extraPackages = lib.optionals (config.fateflix.playback.acceleration == "intel") [
      pkgs.intel-media-driver
      pkgs.intel-vaapi-driver
    ];
  };
}
