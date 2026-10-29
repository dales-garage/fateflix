{ config, lib, ... }:
let
  cfg = config.fateflix.resources;
  workloadMaxMiB = cfg.memoryMiB - cfg.systemReserveMiB;
  memory = value: "${toString value}M";
  media = (builtins.fromJSON config.environment.etc."nixflix/operations.json".text).services;
  enabled = name: config.systemd.services ? ${name} && config.systemd.services.${name}.enable;
  membership =
    slice: names:
    map (name: {
      assertion = (config.systemd.services.${name}.serviceConfig.Slice or null) == slice;
      message = "FateFlix resource budget requires ${name} in ${slice}";
    }) (lib.filter enabled names);
  processing = [
    "nixflix-whisparr-policy"
    "nixflix-import-ingest"
    "nixflix-import-worker"
    "nixflix-remux"
  ];
in
{
  options.fateflix.resources = {
    memoryMiB = lib.mkOption {
      type = lib.types.ints.positive;
      default = 16384;
      description = "Declared VM RAM in MiB; an operator assumption, not detected memory.";
    };
    systemReserveMiB = lib.mkOption {
      type = lib.types.ints.positive;
      default = 2048;
      description = "Headroom outside the aggregate FateFlix workload ceiling, in MiB.";
    };
    workloadHighMiB = lib.mkOption {
      type = lib.types.ints.positive;
      default = 12288;
      description = "Aggregate workload reclaim/throttling watermark in MiB.";
    };
  };
  config = {
    # Hyphens encode slice ancestry: the existing nixflix-staging.slice and
    # these processing/build slices all live below nixflix.slice.
    systemd.slices = {
      nixflix.sliceConfig = {
        MemoryAccounting = true;
        MemoryHigh = memory cfg.workloadHighMiB;
        MemoryMax = memory workloadMaxMiB;
      };
      nixflix-build.sliceConfig = {
        CPUWeight = 25;
        IOWeight = 25;
      };
      nixflix-processing.sliceConfig = {
        CPUWeight = 10;
        IOWeight = 10;
      };
    };
    # Daemon-side builders do not belong to the Comin client's cgroup. Bound
    # both paths; do not rely on a cap on Comin alone to contain Nix builds.
    systemd.services = {
      nix-daemon = lib.mkIf config.nix.enable { serviceConfig.Slice = "nixflix-build.slice"; };
      # The native collector unit exists even when its automatic timer is off.
      nix-gc = lib.mkIf config.nix.enable { serviceConfig.Slice = "nixflix-build.slice"; };
    };
    assertions = [
      {
        assertion = cfg.systemReserveMiB < cfg.memoryMiB;
        message = "FateFlix resource budget must reserve less than declared VM RAM";
      }
      {
        assertion = cfg.workloadHighMiB < workloadMaxMiB;
        message = "FateFlix resource budget high watermark must be below its hard ceiling";
      }
      {
        # Preserve the established media ceiling rather than silently imposing
        # a smaller effective limit through a newly configured parent.
        assertion = workloadMaxMiB >= 12288;
        message = "FateFlix resource budget must retain the existing 12 GiB media ceiling";
      }
      {
        assertion =
          config.systemd.slices.nixflix.enable
          && config.systemd.slices.nixflix.sliceConfig.MemoryHigh == memory cfg.workloadHighMiB
          && config.systemd.slices.nixflix.sliceConfig.MemoryMax == memory workloadMaxMiB;
        message = "Configure fateflix.resources instead of overriding the aggregate slice limits";
      }
    ]
    ++ membership "nixflix-staging.slice" media
    ++ membership "nixflix-processing.slice" processing
    ++ membership "nixflix-build.slice" [
      "nix-daemon"
      "comin"
      "nix-gc"
    ]
    ++ lib.mapAttrsToList (name: container: {
      assertion =
        lib.filter (lib.hasPrefix "--cgroup-parent") container.extraOptions
        == [ "--cgroup-parent=nixflix-staging.slice" ];
      message = "FateFlix resource budget requires container ${name} in nixflix-staging.slice";
    }) config.virtualisation.oci-containers.containers;
  };
}
