{ inputs, fateflixPackagePolicy, ... }:
let
  # Use the host platform for this source-only derivation, including cross-system checks.
  pkgs = import inputs.nixpkgs-host {
    system = "x86_64-linux";
    config =
      (import ../../lib/package-policy.nix { lib = inputs.nixpkgs.lib; }).nixpkgsConfig
        fateflixPackagePolicy;
  };
  source = import ../../integrations/nixflix/default.nix {
    inherit pkgs;
    src = inputs.nixflix;
  };
in
{
  den.aspects.nixflix-api.nixos.imports = [ inputs.self.nixosModules.default ];
  flake = {
    lib.nixflixSource = source;
    lib.buildJellyfinPlugin = { pkgs }: import ../../lib/build-jellyfin-plugin.nix { inherit pkgs; };
    lib.jellyfinPlugins = import ../../lib/jellyfin-plugins.nix { inherit (inputs.nixpkgs) lib; };
    nixosModules.default.imports = [
      "${source}/modules"
      inputs.vpn-confinement.nixosModules.default
    ];
    nixosModules.nixflix.imports = [ inputs.self.nixosModules.default ];
  };
}
