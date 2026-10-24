{ config, lib, ... }:
let
  cfg = config.fateflix.freecore;
in
{
  # Monitoring is an optional integration, never an activation dependency.
  config = lib.mkIf (config.fateflix.host.role == "production" && config.nixflix.notifiarr.enable) {
    nixflix.notifiarr.settings.service =
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
        ];
  };
}
