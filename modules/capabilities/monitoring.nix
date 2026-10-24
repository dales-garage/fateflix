{ den, ... }: {
  den.aspects.monitoring = {
    includes = [ den.aspects.media ];
    nixos = { config, lib, ... }: {
      imports = [ ../../capabilities/monitoring/notifiarr.nix ];
      nixflix.notifiarr.enable = lib.mkDefault (config.fateflix.host.role == "production");
    };
  };
}
