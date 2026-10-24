{ config, lib, ... }: {
  # This payload runs on the NAS; private middleware/webhook state stays there.
  # Retain the installed filename for existing operator commands.
  config = lib.mkIf (config.fateflix.host.role == "production") {
    environment.etc."nixflix/freecore-notifiarr.py".source = ./scripts/freecore-notifier.py;
  };
}
