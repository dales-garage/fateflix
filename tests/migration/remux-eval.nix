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
  imports = cfg.systemd.services.nixflix-import-worker;
  importSettings = builtins.fromJSON (
    builtins.unsafeDiscardStringContext cfg.environment.etc."nixflix/imports.json".text
  );
  withoutImports =
    (host.extendModules { modules = [ { nixflixHost.imports.enable = pkgs.lib.mkForce false; } ]; })
    .config;
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
assert imports.serviceConfig.CPUQuota == "150%";
assert imports.serviceConfig.MemoryMax == "3G";
assert imports.serviceConfig.MemorySwapMax == 0;
assert imports.serviceConfig.KillMode == "control-group";
assert imports.restartIfChanged == false;
assert imports.serviceConfig.ReadWritePaths == [ "/data/media/porn" ];
assert importSettings.crf == 28 && importSettings.preset == 8;
assert importSettings.reserveBytes == 536870912000;
assert cfg.systemd.services.nixflix-import-ingest.serviceConfig.InaccessiblePaths == [ "/data" ];
assert cfg.systemd.timers.nixflix-import-worker.timerConfig.OnUnitInactiveSec == "1m";
assert !(staging.config.systemd.services ? nixflix-import-worker);
assert !(withoutImports.systemd.services ? nixflix-import-worker);
pkgs.runCommand "remux-eval" { } "touch $out"
