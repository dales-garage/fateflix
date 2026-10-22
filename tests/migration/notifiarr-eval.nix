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
assert !staging.config.nixflix.notifiarr.enable;
assert !(staging.config.systemd.services ? notifiarr);
assert builtins.length client.settings.sonarr == 2;
assert builtins.length client.settings.radarr == 2;
assert builtins.length client.settings.readarr == 1;
assert withoutReadarr.nixflix.notifiarr.settings.readarr == [ ];
assert client.settings.plex.token._secret == "/var/lib/plex/Plex Media Server/Preferences.xml";
assert unit.serviceConfig.DynamicUser;
assert unit.serviceConfig.RuntimeDirectoryMode == "0700";
assert pkgs.lib.hasPrefix "+" unit.serviceConfig.ExecStartPre;
assert cfg.systemd.services.seerr.preStart == "";
assert cfg.networking.firewall.allowedTCPPorts == [ 22 ];
assert !(builtins.elem 5454 cfg.networking.firewall.allowedTCPPorts);
pkgs.runCommand "notifiarr-eval" { } "touch $out"
