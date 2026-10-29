{ config, lib, ... }: {
  # Comin owns deployment/generation retention. Collect only unreachable paths;
  # never delete profiles or retained rollback roots as part of host maintenance.
  nix.gc = {
    automatic = lib.mkDefault true;
    dates = lib.mkDefault "Sun *-*-* 04:15:00";
    randomizedDelaySec = lib.mkDefault "45m";
    persistent = lib.mkDefault true;
    options = lib.mkDefault "";
  };
  nix.settings = {
    min-free = lib.mkDefault config.fateflix.storage.capacity.root.critical;
    max-free = lib.mkDefault config.fateflix.storage.capacity.root.warning;
  };
  assertions = [
    {
      assertion = config.nix.gc.options == "";
      message = "FateFlix store GC must leave nix.gc.options empty; Comin owns generation retention and rollback roots.";
    }
    {
      assertion =
        builtins.isInt config.nix.settings.min-free
        && builtins.isInt config.nix.settings.max-free
        && config.nix.settings.min-free >= 0
        && config.nix.settings.max-free > config.nix.settings.min-free;
      message = "FateFlix Nix store GC requires integer byte counts with 0 <= min-free < max-free.";
    }
  ];
  systemd.services.nix-gc.serviceConfig = {
    Nice = 19;
    CPUWeight = 10;
    IOWeight = 10;
    IOSchedulingClass = "idle";
  };
}
