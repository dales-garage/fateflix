{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  python = pkgs.python3.withPackages (p: [ p.pyyaml ]);
  health = pkgs.writeShellApplication {
    name = "nixflix-health";
    runtimeInputs = [
      pkgs.systemd
      pkgs.util-linux
    ];
    text = ''
      exec ${python}/bin/python3 ${../../scripts/gitops-health.py} "$@"
    '';
  };
  hook = pkgs.writeShellScript "nixflix-comin-hook" ''
    ${lib.getExe health} hook
    ${pkgs.systemd}/bin/systemctl start --no-block nixflix-health.service
  '';
in
{
  imports = [ inputs.comin.nixosModules.comin ];
  config = lib.mkIf config.nixflixHost.production.enable {
    services.comin = {
      enable = true;
      package = inputs.comin.packages.${pkgs.stdenv.hostPlatform.system}.comin;
      hostname = "nixflix-production";
      remotes = [
        {
          name = "origin";
          url = "https://github.com/declarative-dale/nixflix.git";
          branches.main = {
            name = "main";
            operation = "switch";
          };
          branches.testing.name = "";
          poller.period = 60;
        }
      ];
      exporter = {
        listen_address = "127.0.0.1";
        openFirewall = false;
      };
      buildTimeout = 7200;
      buildAttemptsLimit = 3;
      buildRetryTimer = 300;
      postBuildCommand = hook;
      postDeploymentCommand = hook;
      retention = {
        deployment_boot_entry_capacity = 3;
        deployment_successful_capacity = 3;
        deployment_any_capacity = 5;
      };
    };
    environment.systemPackages = [ health ];
    environment.etc."nixflix/gitops-services.json".source = ./local-services.json;
    environment.etc."nixos/README.gitops".text = ''
      Managed by Comin from declarative-dale/nixflix main.
      Production output: nixosConfigurations.nixflix-production.
      Merge reviewed PRs; do not run an independent nixos-rebuild here.
      Status: sudo comin status; sudo nixflix-health check
      Recovery: see docs/gitops.md in the repository. Suspend Comin first.
    '';
    systemd.tmpfiles.rules = [ "d /var/lib/nixflix-gitops 0700 root root -" ];
    systemd.services.nixflix-health = {
      description = "Check running nixflix services and GitOps deployment health";
      after = [
        "network-online.target"
        "nixflix-staging.target"
      ];
      wants = [ "network-online.target" ];
      path = [
        pkgs.systemd
        pkgs.util-linux
      ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${lib.getExe health} check --wait 120";
        TimeoutStartSec = 300;
        UMask = "0077";
      };
    };
    systemd.timers.nixflix-health = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2m";
        OnUnitInactiveSec = "5m";
      };
    };
    systemd.services.nixflix-health-endpoint = {
      description = "Loopback-only deployment health for Notifiarr";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        ExecStart = "${lib.getExe health} serve";
        Restart = "on-failure";
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };
    nixflix.notifiarr.settings.service = [
      {
        name = "nixflix-gitops";
        type = "http";
        check = "http://127.0.0.1:9199/health";
        expect = "200";
        interval = "5m";
        timeout = "10s";
      }
    ];
  };
}
