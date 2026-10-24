{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  localServices = builtins.fromJSON (builtins.readFile ./local-services.json);
  healthManifest = localServices // {
    services = lib.filterAttrs (
      name: _: name != "sabnzbd" || config.nixflix.usenetClients.sabnzbd.enable
    ) localServices.services;
    monitoring.notifiarr = config.nixflix.notifiarr.enable;
  };
  python = pkgs.python3.withPackages (p: [ p.pyyaml ]);
  # Keep CI/remux tooling out of the health closure. Python needs these four
  # sibling modules, not every script in the repository.
  runtime = pkgs.runCommand "nixflix-health-runtime" { } ''
    install -Dm444 ${../../scripts/gitops-health.py} "$out/gitops-health.py"
    install -Dm444 ${../../scripts/nixflix_ops.py} "$out/nixflix_ops.py"
    install -Dm444 ${../../scripts/nixflix_playback.py} "$out/nixflix_playback.py"
    install -Dm444 ${../../scripts/nixflix_retention.py} "$out/nixflix_retention.py"
  '';
  health = pkgs.writeShellApplication {
    name = "nixflix-health";
    runtimeInputs = [
      pkgs.systemd
      pkgs.util-linux
      pkgs.podman
    ];
    text = ''
      exec ${python}/bin/python3 ${runtime}/gitops-health.py "$@"
    '';
  };
  hook = pkgs.writeShellScript "nixflix-comin-hook" ''
    ${lib.getExe health} hook
    ${pkgs.systemd}/bin/systemctl start --no-block nixflix-health.service
  '';
in
{
  imports = [ inputs.comin.nixosModules.comin ];
  options.nixflixHost.capacity =
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
  config = lib.mkIf config.nixflixHost.production.enable {
    assertions =
      map
        (name: {
          assertion =
            config.nixflixHost.capacity.${name}.warning > config.nixflixHost.capacity.${name}.critical;
          message = "${name} capacity warning must exceed critical";
        })
        [
          "nas"
          "root"
        ];
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
    environment.etc."nixflix/gitops-services.json".text = builtins.toJSON healthManifest;
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
        # Readiness retries (120s), reconciliation completion (245s), and the
        # remaining bounded HTTP checks must all fit inside the unit budget.
        TimeoutStartSec = 480;
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
    systemd.services.nixflix-playback = {
      description = "Synthetic playback diagnostics after relevant deployment changes";
      after = [ "podman-stash.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${lib.getExe health} playback --if-changed";
        TimeoutStartSec = 210;
        TimeoutStopSec = 5;
        UMask = "0077";
      };
    };
    systemd.timers.nixflix-playback = {
      wantedBy = [ "timers.target" ];
      timerConfig.OnBootSec = "3m";
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
    ]
    ++
      map
        (name: {
          name = "nixflix-advisory-${name}";
          type = "http";
          check = "http://127.0.0.1:9199/advisory/${name}";
          expect = "200";
          interval = "5m";
          timeout = "10s";
        })
        [
          "capacity-warning"
          "capacity-critical"
          "sonarr"
          "sonarr-4k"
          "radarr"
          "radarr-4k"
          "lidarr"
          "prowlarr"
          "readarr"
          "whisparr"
        ];
  };
}
