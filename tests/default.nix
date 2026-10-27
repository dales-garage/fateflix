{
  lib,
  nixosModules,
  nixflixSource,
  pkgs ? import <nixpkgs> { inherit system; },
  system ? builtins.currentSystem,
}:
{
  # Import all test modules
  vm-tests = import ./vm-tests {
    inherit
      system
      pkgs
      nixosModules
      nixflixSource
      lib
      ;
  };
  unit-tests = import ./unit-tests { inherit system pkgs nixosModules; };
}
