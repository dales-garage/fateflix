{ config, lib, ... }: {
  # Run VM integration checks on hosted CI rather than the production guest.
  config = lib.mkIf (config.fateflix.host.role == "production") {
    nix.settings.system-features = lib.mkForce [
      "benchmark"
      "big-parallel"
    ];
  };
}
