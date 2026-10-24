{
  inputs,
  lib,
  pkgs,
  ...
}:
let
  # Keep the operating-system modules on 26.05. The separate, locked package
  # set carries application releases that have not reached that channel yet.
  media = import inputs.nixpkgs-media {
    inherit (pkgs.stdenv.hostPlatform) system;
    config.allowUnfree = true;
  };
in
{
  boot.kernelPackages = media.linuxPackages_6_18;
  services = {
    sabnzbd.package = media.sabnzbd;
    bazarr.package = media.bazarr;
    tautulli.package = media.tautulli;
    audiobookshelf.package = media.audiobookshelf;
    plex.package = media.plex;
    # 3.5.1 updates the bundled Node runtime requirement without changing the
    # dependency lock. Use the fresh package set's patched Node 22 runtime.
    seerr.package =
      if lib.versionAtLeast media.seerr.version "3.5.1" then
        media.seerr
      else
        media.seerr.overrideAttrs {
          version = "3.5.1";
          src = media.fetchFromGitHub {
            owner = "seerr-team";
            repo = "seerr";
            tag = "v3.5.1";
            hash = "sha256-qbKHypQy1laLRqC2BAfM4AAQsxfjY/kXTHTCiF3tDxA=";
          };
        };
  };
}
