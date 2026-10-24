{ config, lib, ... }: {
  options.fateflix.storage.capacity =
    let
      threshold =
        warning: critical:
        lib.mkOption {
          type = lib.types.submodule {
            options = {
              warning = lib.mkOption {
                type = lib.types.ints.positive;
                default = warning;
              };
              critical = lib.mkOption {
                type = lib.types.ints.positive;
                default = critical;
              };
            };
          };
          default = { };
        };
    in
    {
      nas = threshold 1099511627776 536870912000;
      root = threshold 21474836480 10737418240;
      probeMaxAge = lib.mkOption {
        type = lib.types.ints.positive;
        default = 180;
      };
    };
  config = {
    assertions =
      map
        (name: {
          assertion =
            config.fateflix.storage.capacity.${name}.warning
            > config.fateflix.storage.capacity.${name}.critical;
          message = "${name} capacity warning must exceed critical";
        })
        [
          "nas"
          "root"
        ];
  };
}
