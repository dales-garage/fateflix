{
  lib,
  nixosModules,
  nixflixSource,
  quadletModule,
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
      quadletModule
      lib
      ;
  };
  unit-tests = import ./unit-tests { inherit system pkgs nixosModules; };
}
