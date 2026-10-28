{
  inputs,
  fateflixPackagePolicy,
  lib,
  pkgs,
  ...
}:
let
  # Keep the operating-system modules on 26.05. The separate, locked package
  # set carries application releases that have not reached that channel yet.
  media = import inputs.nixpkgs-media {
    inherit (pkgs.stdenv.hostPlatform) system;
    config = (import ../../lib/package-policy.nix { inherit lib; }).nixpkgsConfig fateflixPackagePolicy;
  };
in
{
  boot.kernelPackages = media.linuxPackages_6_18;
  services = {
    sabnzbd.package = media.sabnzbd;
    # Bazarr 1.6.2 explicitly supports Python through 3.13, while this package
    # set defaults to 3.14. Track current patches of the supported interpreter.
    bazarr.package = media.bazarr.override { python3Packages = media.python313Packages; };
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
