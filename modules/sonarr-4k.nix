{ config, lib, ... }:
let
  cfg = config.nixflix.sonarr-4k;
in
{
  imports = [ (import ./arr-common/mkArrServiceModule.nix { serviceName = "sonarr-4k"; }) ];
  config.nixflix.sonarr-4k = {
    group = lib.mkDefault "media";
    mediaDirs = lib.mkDefault [ "${config.nixflix.mediaDir}/tv-4k" ];
    config = {
      apiVersion = lib.mkDefault "v3";
      hostConfig = {
        port = lib.mkDefault 8991;
        branch = lib.mkDefault "main";
      };
      rootFolders = lib.mkDefault (map (path: { inherit path; }) cfg.mediaDirs);
    };
  };
}
