{ config, lib, ... }:
let
  policy = import ../../lib/package-policy.nix { inherit lib; };
in
{
  options.fateflix.packagePolicy = lib.mkOption {
    type = policy.type;
    default = { };
    description = ''
      Shared package policy applied before constructing host, media and tooling
      Nixpkgs. Unfree packages are allowed by default. Denied enabled packages
      fail evaluation rather than silently disabling capabilities.
    '';
  };
  config._module.args.fateflixPackagePolicy = config.fateflix.packagePolicy;
}
