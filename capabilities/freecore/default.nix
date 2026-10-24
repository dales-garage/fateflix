{ lib, ... }: {
  imports = [
    ./nas.nix
    ./notifier.nix
  ];
  options.fateflix.freecore = {
    address = lib.mkOption {
      type = lib.types.str;
      default = "freecore";
      description = "FreeCORE NAS address for independent availability checks.";
    };
    interval = lib.mkOption {
      type = lib.types.str;
      default = "1m";
      description = "Notifiarr polling interval for NAS availability.";
    };
    timeout = lib.mkOption {
      type = lib.types.str;
      default = "5s";
      description = "Timeout for each NAS listener check.";
    };
  };
}
