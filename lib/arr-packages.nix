# Shared by the hosts and hosted integration tests so they exercise the same apps.
{ pkgs, media }:
let
  prowlarrRelease = builtins.fromJSON (builtins.readFile ../pkgs/prowlarr-upstream/sources.json);
in
{
  prowlarr =
    if pkgs.lib.versionAtLeast media.prowlarr.version prowlarrRelease.version then
      media.prowlarr
    else
      media.callPackage ../pkgs/prowlarr-upstream { };
  inherit (media) radarr lidarr;
}
