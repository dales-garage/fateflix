{
  pkgs,
  host,
  staging,
}:
let
  inherit (pkgs) lib;
  cfg = host.config;
  # Exercise policy failures without repeatedly evaluating an entire appliance.
  # Real NixOS composition and capability omission are checked below and by
  # settings-eval respectively; these fixtures model only the policy's inputs.
  fixture =
    module:
    (lib.evalModules {
      modules = [
        ../../hosts/nixflix/resources.nix
        ({ config, lib, ... }: {
          options = {
            assertions = lib.mkOption {
              type = lib.types.listOf lib.types.unspecified;
              default = [ ];
            };
            environment.etc = lib.mkOption { type = lib.types.attrsOf lib.types.unspecified; };
            nix.enable = lib.mkOption {
              type = lib.types.bool;
              default = true;
            };
            nix.gc.automatic = lib.mkOption {
              type = lib.types.bool;
              default = false;
            };
            virtualisation.oci-containers.containers = lib.mkOption {
              type = lib.types.attrsOf (
                lib.types.submodule {
                  options.extraOptions = lib.mkOption { type = lib.types.listOf lib.types.str; };
                }
              );
            };
            systemd.slices = lib.mkOption {
              type = lib.types.attrsOf (
                lib.types.submodule {
                  options = {
                    enable = lib.mkOption {
                      type = lib.types.bool;
                      default = true;
                    };
                    sliceConfig = lib.mkOption { type = lib.types.attrsOf lib.types.unspecified; };
                  };
                }
              );
            };
            systemd.services = lib.mkOption {
              type = lib.types.attrsOf (
                lib.types.submodule {
                  options = {
                    enable = lib.mkOption {
                      type = lib.types.bool;
                      default = true;
                    };
                    serviceConfig = lib.mkOption {
                      type = lib.types.attrsOf lib.types.unspecified;
                      default = { };
                    };
                  };
                }
              );
            };
          };
          config = {
            environment.etc."nixflix/operations.json".text = builtins.toJSON {
              services = [
                "plex"
                "podman-example"
              ];
            };
            systemd.services = {
              # Native NixOS defines these whenever Nix is enabled, even when
              # the garbage-collection timer is disabled.
              nix-daemon = lib.mkIf config.nix.enable { };
              nix-gc = lib.mkIf config.nix.enable { };
              plex.serviceConfig.Slice = "nixflix-staging.slice";
              podman-example.serviceConfig.Slice = "nixflix-staging.slice";
              comin.serviceConfig.Slice = "nixflix-build.slice";
              nixflix-import-worker.serviceConfig.Slice = "nixflix-processing.slice";
            };
            virtualisation.oci-containers.containers.example.extraOptions = [
              "--cgroup-parent=nixflix-staging.slice"
            ];
          };
        })
        module
      ];
    }).config;
  valid = config: builtins.all (a: a.assertion) config.assertions;
  invalid = module: !valid (fixture module);
  rejectedType =
    value:
    !(builtins.tryEval (fixture { fateflix.resources.memoryMiB = value; }).fateflix.resources.memoryMiB)
    .success;
  defaults = fixture { };
  gc = fixture { nix.gc.automatic = true; };
  withoutNix = fixture { nix.enable = false; };
in
assert builtins.all valid [
  cfg
  staging.config
];
assert cfg.fateflix.resources.memoryMiB == 16384;
assert cfg.fateflix.resources.systemReserveMiB == 2048;
assert cfg.systemd.slices.nixflix.sliceConfig.MemoryMax == "14336M";
assert cfg.systemd.slices.nixflix.sliceConfig.MemoryHigh == "12288M";
assert cfg.systemd.slices.nixflix-staging.sliceConfig.MemoryMax == "12G";
assert cfg.systemd.slices.nixflix-staging.sliceConfig.MemoryHigh == "10G";
assert cfg.systemd.services.nixflix-import-worker.serviceConfig.MemoryMax == "3G";
assert cfg.systemd.services.nixflix-remux.serviceConfig.MemoryMax == "768M";
assert cfg.systemd.services.comin.serviceConfig.Slice == "nixflix-build.slice";
assert !cfg.systemd.services.comin.restartIfChanged;
assert cfg.systemd.services.nix-daemon.serviceConfig.Slice == "nixflix-build.slice";
assert !cfg.systemd.services.nix-daemon.stopIfChanged;
assert cfg.systemd.services.nix-gc.serviceConfig.Slice == "nixflix-build.slice";
assert cfg.systemd.services.nixflix-import-worker.serviceConfig.Slice == "nixflix-processing.slice";
assert cfg.systemd.services.nixflix-remux.serviceConfig.Slice == "nixflix-processing.slice";
assert !(staging.config.systemd.services ? comin);
assert valid defaults;
assert defaults.systemd.services.nix-gc.serviceConfig.Slice == "nixflix-build.slice";
assert valid gc && gc.systemd.services.nix-gc.serviceConfig.Slice == "nixflix-build.slice";
assert valid withoutNix;
assert !(withoutNix.systemd.services ? nix-gc);
assert !(withoutNix.systemd.services ? nix-daemon);
assert valid (fixture {
  fateflix.resources.memoryMiB = 32768;
});
assert valid (fixture {
  systemd.services.nixflix-import-worker = {
    enable = false;
    serviceConfig.Slice = lib.mkForce "system.slice";
  };
});
assert builtins.all rejectedType [
  0
  (-1)
  "16384"
];
assert builtins.all invalid [
  { fateflix.resources.systemReserveMiB = 16384; }
  { fateflix.resources.workloadHighMiB = 14336; }
  { fateflix.resources.memoryMiB = 12288; }
  { systemd.slices.nixflix.sliceConfig.MemoryMax = lib.mkForce "infinity"; }
  { systemd.slices.nixflix.sliceConfig.MemoryHigh = lib.mkForce "infinity"; }
  { systemd.slices.nixflix.enable = false; }
  { systemd.services.nix-daemon.serviceConfig.Slice = lib.mkForce "system.slice"; }
  { systemd.services.nix-gc.serviceConfig.Slice = lib.mkForce "system.slice"; }
  { systemd.services.comin.serviceConfig.Slice = lib.mkForce "system.slice"; }
  { systemd.services.nixflix-import-worker.serviceConfig.Slice = lib.mkForce "system.slice"; }
  { systemd.services.plex.serviceConfig.Slice = lib.mkForce "system.slice"; }
  { systemd.services.podman-example.serviceConfig.Slice = lib.mkForce "system.slice"; }
  { virtualisation.oci-containers.containers.example.extraOptions = lib.mkForce [ ]; }
  {
    virtualisation.oci-containers.containers.example.extraOptions = [ "--cgroup-parent=system.slice" ];
  }
  {
    nix.gc.automatic = true;
    systemd.services.nix-gc.serviceConfig.Slice = lib.mkForce "system.slice";
  }
];
pkgs.runCommand "resources-eval" { } "touch $out"
