{
  lib,
  nixosModules,
  nixflixSource,
  pkgs ? import <nixpkgs> { inherit system; },
  system ? builtins.currentSystem,
}:
let
  testFiles = builtins.filter (name: name != "default.nix" && pkgs.lib.hasSuffix ".nix" name) (
    builtins.attrNames (builtins.readDir ./.)
  );

  testNameFromFile = file: pkgs.lib.removeSuffix ".nix" file;

  importTest =
    file:
    let
      test = import (./. + "/${file}") (
        {
          inherit system pkgs;
          nixosModules = {
            imports = [ nixosModules ];
            # Concurrent Arr migrations can flood the emulated serial console and
            # stall the guest kernel. Retain full logs in the journal, forwarding
            # only warnings to the console across all VM integration tests.
            services.journald.settings.Journal.MaxLevelConsole = lib.mkForce "warning";
          };
        }
        // lib.optionalAttrs (file == "lidarr-basic.nix") { inherit nixflixSource; }
      );
      fileContents = builtins.readFile (./. + "/${file}");
    in
    test
    // {
      passthru = (test.passthru or { }) // {
        meta = (test.passthru.meta or { }) // {
          requiresNetwork = lib.boolToString (
            builtins.match ".*networking\\.useDHCP[[:space:]]*=[[:space:]]*true.*" fileContents != null
          );
        };
      };
    };
in
builtins.listToAttrs (
  map (file: {
    name = testNameFromFile file;
    value = importTest file;
  }) testFiles
)
