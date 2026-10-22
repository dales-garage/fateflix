{
  pkgs,
  host,
  staging,
}:
let
  cfg = host.config;
  remote = builtins.head cfg.services.comin.remotes;
in
assert cfg.services.comin.enable;
assert !staging.config.services.comin.enable;
assert cfg.services.comin.hostname == "nixflix-production";
assert remote.url == "https://github.com/declarative-dale/nixflix.git";
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
