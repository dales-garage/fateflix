{
  den.aspects.monitoring.nixos = { config, lib, ... }: {
    imports = [ ../_modules/monitoring/notifiarr.nix ];
    nixflix.notifiarr.enable = lib.mkDefault (config.fateflix.host.role == "production");
  };
}
