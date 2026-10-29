{
  pkgs,
  host,
  staging,
}:
let
  cfg = host.config;
  remote = builtins.head cfg.services.comin.remotes;
  gcPolicy =
    c:
    c.nix.gc.automatic
    && c.nix.gc.options == ""
    && c.nix.gc.dates == [ "Sun *-*-* 04:15:00" ]
    && c.nix.gc.randomizedDelaySec == "45m"
    && c.nix.gc.persistent
    && c.nix.settings.min-free == c.fateflix.storage.capacity.root.critical
    && c.nix.settings.max-free == c.fateflix.storage.capacity.root.warning
    && c.systemd.services.nix-gc.script == "exec ${c.nix.package.out}/bin/nix-collect-garbage "
    && c.systemd.timers.nix-gc.timerConfig.OnCalendar == [ "Sun *-*-* 04:15:00" ]
    && c.systemd.timers.nix-gc.timerConfig.RandomizedDelaySec == "45m"
    && c.systemd.timers.nix-gc.timerConfig.Persistent
    && c.systemd.services.nix-gc.serviceConfig.Nice == 19
    && c.systemd.services.nix-gc.serviceConfig.CPUWeight == 10
    && c.systemd.services.nix-gc.serviceConfig.IOWeight == 10
    && c.systemd.services.nix-gc.serviceConfig.IOSchedulingClass == "idle";
  custom =
    (host.extendModules {
      modules = [
        {
          nix.gc = {
            automatic = false;
            dates = "Sat *-*-* 05:00:00";
            randomizedDelaySec = "0";
            persistent = false;
          };
          nix.settings = {
            min-free = 0;
            max-free = 1073741824;
          };
        }
      ];
    }).config;
  invalid =
    (host.extendModules {
      modules = [
        {
          nix.gc.options = "--delete-old";
          nix.settings = {
            min-free = 20;
            max-free = 10;
          };
        }
      ];
    }).config;
in
assert gcPolicy cfg && gcPolicy staging.config;
assert !custom.nix.gc.automatic && !custom.nix.gc.persistent;
assert !(custom.systemd.timers ? nix-gc);
assert custom.nix.gc.dates == [ "Sat *-*-* 05:00:00" ];
assert custom.nix.gc.randomizedDelaySec == "0";
assert custom.nix.settings.min-free == 0 && custom.nix.settings.max-free == 1073741824;
assert builtins.any (
  a: !a.assertion && pkgs.lib.hasPrefix "FateFlix store GC" a.message
) invalid.assertions;
assert builtins.any (
  a: !a.assertion && pkgs.lib.hasPrefix "FateFlix Nix store GC" a.message
) invalid.assertions;
assert cfg.services.comin.enable;
assert !(staging.config.services ? comin);
assert cfg.services.comin.hostname == "nixflix-production";
assert remote.url == "https://github.com/dales-garage/fateflix.git";
assert remote.branches.main.name == "main";
assert remote.branches.main.operation == "switch";
assert remote.branches.testing.name == "";
assert remote.auth.access_token_path == "";
assert cfg.services.comin.exporter.listen_address == "127.0.0.1";
assert !cfg.services.comin.exporter.openFirewall;
assert cfg.services.comin.retention.deployment_boot_entry_capacity == 3;
assert !(builtins.elem 9199 cfg.networking.firewall.allowedTCPPorts);
assert builtins.any (
  s: s.name == "nixflix-gitops" && s.expect == "200"
) cfg.nixflix.notifiarr.settings.service;
pkgs.runCommand "gitops-eval" { } "touch $out"
