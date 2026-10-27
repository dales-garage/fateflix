{
  pkgs ? import <nixpkgs> { },
}:
let
  lock = builtins.fromJSON (builtins.readFile ./flake.lock);
  fetchInput =
    name:
    let
      pin = lock.nodes.${name}.locked;
    in
    fetchTarball {
      url = "https://github.com/${pin.owner}/${pin.repo}/archive/${pin.rev}.tar.gz";
      sha256 = pin.narHash;
    };
  source = import ./integrations/nixflix/default.nix {
    inherit pkgs;
    src = fetchInput "nixflix";
  };
  nixflixModule.imports = [
    "${source}/modules"
    "${fetchInput "vpn-confinement"}/modules/vpn-netns.nix"
  ];
in
{
  nixosModules.default = nixflixModule;
  nixosModules.nixflix = nixflixModule;
  lib.jellyfinPlugins = import ./lib/jellyfin-plugins.nix { inherit (pkgs) lib; };
  lib.buildJellyfinPlugin = import ./lib/build-jellyfin-plugin.nix { inherit pkgs; };
}
