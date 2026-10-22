{
  pkgs,
  host,
  staging,
}:
let
  cfg = host.config;
  disabled =
    (host.extendModules { modules = [ { nixflixHost.remux.enable = pkgs.lib.mkForce false; } ]; })
    .config;
  settings = builtins.fromJSON (
    builtins.unsafeDiscardStringContext cfg.environment.etc."nixflix/remux.json".text
  );
  service = cfg.systemd.services.nixflix-remux;
in
assert service.serviceConfig.Restart == "no";
assert service.wantedBy == [ ];
assert service.restartIfChanged == false;
assert service.serviceConfig.ProtectSystem == "strict";
assert service.serviceConfig.ReadWritePaths == [ "/data/media/porn" ];
assert service.serviceConfig.KillMode == "control-group";
assert service.serviceConfig.StateDirectoryMode == "0700";
assert settings.reserveBytes == 536870912000;
assert settings.stashRoot == "/data" && settings.mediaRoot == "/data/media/porn";
assert settings.requireMount;
assert !(staging.config.systemd.services ? nixflix-remux);
assert !(disabled.systemd.services ? nixflix-remux);
pkgs.runCommand "remux-eval" { } "touch $out"
