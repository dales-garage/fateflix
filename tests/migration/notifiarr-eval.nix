{
  pkgs,
  host,
  staging,
}:
let
  cfg = host.config;
  client = cfg.nixflix.notifiarr;
  unit = cfg.systemd.services.notifiarr;
  withoutReadarr =
    (host.extendModules { modules = [ { services.readarr.enable = pkgs.lib.mkForce false; } ]; })
    .config;
in
assert client.enable;
assert cfg.fateflix.freecore.address == "10.69.0.10";
assert
  builtins.readFile cfg.environment.etc."nixflix/freecore-notifiarr.py".source
  == builtins.readFile ../../capabilities/freecore/scripts/freecore-notifier.py;
assert !(staging.config.environment.etc ? "nixflix/freecore-notifiarr.py");
assert builtins.all (check: !(pkgs.lib.hasPrefix "FreeCORE " check.name)) (
  staging.config.nixflix.notifiarr.settings.service or [ ]
);
assert !staging.config.nixflix.notifiarr.enable;
assert !(staging.config.systemd.services ? notifiarr);
assert builtins.length client.settings.sonarr == 2;
assert builtins.length client.settings.radarr == 2;
assert builtins.length client.settings.readarr == 1;
assert withoutReadarr.nixflix.notifiarr.settings.readarr == [ ];
assert client.settings.plex.token._secret == "/var/lib/plex/Plex Media Server/Preferences.xml";
assert pkgs.lib.hasSuffix " --local-only"
  cfg.systemd.services.notifiarr-connections.serviceConfig.ExecStart;
assert pkgs.lib.hasSuffix " --plex-webhooks-only"
  cfg.systemd.services.notifiarr-plex-webhooks.serviceConfig.ExecStart;
assert cfg.systemd.timers.notifiarr-plex-webhooks.timerConfig.OnUnitInactiveSec == "5m";
assert cfg.systemd.timers.notifiarr-plex-webhooks.timerConfig.OnActiveSec == "5m";
assert cfg.systemd.services.notifiarr-plex-webhooks.wantedBy == [ ];
assert !(builtins.elem "plex.service" cfg.systemd.services.notifiarr-plex-webhooks.wants);
assert !(staging.config.systemd.services ? notifiarr-plex-webhooks);
assert unit.serviceConfig.DynamicUser;
assert unit.serviceConfig.RuntimeDirectoryMode == "0700";
assert pkgs.lib.hasPrefix "+" unit.serviceConfig.ExecStartPre;
assert cfg.systemd.services.seerr.preStart == "";
assert cfg.networking.firewall.allowedTCPPorts == [ 22 ];
assert !(builtins.elem 5454 cfg.networking.firewall.allowedTCPPorts);
assert builtins.all (
  check:
  check.type == "tcp"
  && check.interval == "1m"
  && check.timeout == "5s"
  && builtins.elem check.check [
    "10.69.0.10:443"
    "10.69.0.10:445"
  ]
) (builtins.filter (check: pkgs.lib.hasPrefix "FreeCORE " check.name) client.settings.service);
assert
  builtins.length (
    builtins.filter (check: pkgs.lib.hasPrefix "FreeCORE " check.name) client.settings.service
  ) == 2;
pkgs.runCommand "notifiarr-eval" { } "touch $out"
