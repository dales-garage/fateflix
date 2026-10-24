{ config, lib, ... }:
let
  cfg = config.fateflix.monitoring.freecore;
in
{
  options.fateflix.monitoring.freecore = {
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
  config = lib.mkIf (config.fateflix.host.role == "production") {
    # This standalone payload runs on FreeCORE, where its local middleware API
    # exists. Its webhook/configuration/state remain private runtime NAS files.
    environment.etc."nixflix/freecore-notifiarr.py".source = ../../../scripts/freecore-notifiarr.py;
    nixflix.notifiarr.settings.service = lib.mkIf config.nixflix.notifiarr.enable (
      map
        (service: {
          name = "FreeCORE ${service.name}";
          type = "tcp";
          check = "${cfg.address}:${toString service.port}";
          inherit (cfg) interval timeout;
        })
        [
          {
            name = "SMB";
            port = 445;
          }
          {
            name = "Web";
            port = 443;
          }
        ]
    );
  };
}
