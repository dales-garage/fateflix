{ config, lib, ... }:
let
  cfg = config.nixflix.radarr-4k;
in
{
  imports = [ (import ./arr-common/mkArrServiceModule.nix { serviceName = "radarr-4k"; }) ];
  config.nixflix.radarr-4k = {
    group = lib.mkDefault "media";
    mediaDirs = lib.mkDefault [ "${config.nixflix.mediaDir}/movies-4k" ];
    config = {
      apiVersion = lib.mkDefault "v3";
      hostConfig = {
        port = lib.mkDefault 7880;
        branch = lib.mkDefault "master";
      };
      rootFolders = lib.mkDefault (map (path: { inherit path; }) cfg.mediaDirs);
    };
  };
}
