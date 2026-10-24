{
  config,
  lib,
  utils,
  pkgs,
  ...
}:
let
  cfg = config.fateflix.imports.conversion;
  runtime = pkgs.runCommand "nixflix-import-runtime" { } ''
    mkdir -p $out
    install -m 0444 ${../../../scripts/nixflix_imports.py} $out/nixflix_imports.py
    install -m 0444 ${../../../scripts/nixflix_remux.py} $out/nixflix_remux.py
  '';
  command = pkgs.writeShellScriptBin "nixflix-imports" ''
    exec ${pkgs.python3}/bin/python3 ${runtime}/nixflix_imports.py "$@"
  '';
  hook = pkgs.writeShellScriptBin "nixflix-whisparr-import-hook" ''
    exec ${command}/bin/nixflix-imports enqueue
  '';
  conditions = [
    "!/var/lib/nixflix-gitops/holds/all"
    "!/var/lib/nixflix-gitops/holds/whisparr"
    "!/var/lib/nixflix-gitops/holds/podman-stash"
  ];
  common = {
    Type = "oneshot";
    StateDirectory = "nixflix-imports";
    StateDirectoryMode = "0700";
    UMask = "0077";
    NoNewPrivileges = true;
    ProtectHome = true;
    ProtectSystem = "strict";
    PrivateTmp = true;
    KillMode = "control-group";
  };
in
{
  options.fateflix.imports.conversion = {
    crf = lib.mkOption {
      type = lib.types.ints.between 0 63;
      default = 28;
      description = "SVT-AV1 constant quality; balanced default, lower is higher quality.";
    };
    preset = lib.mkOption {
      type = lib.types.ints.between 0 13;
      default = 8;
      description = "SVT-AV1 encoding preset.";
    };
    cpuQuota = lib.mkOption {
      type = lib.types.str;
      default = "150%";
      description = "Maximum CPU time used by the conversion worker.";
    };
    reserveBytes = lib.mkOption {
      type = lib.types.ints.positive;
      default = 536870912000;
      description = "NAS free-space reserve retained before conversion.";
    };
  };
  config = lib.mkIf (config.fateflix.host.role == "production") {
    environment.systemPackages = [ command ];
    environment.etc."nixflix/imports.json".text = builtins.toJSON {
      url = "http://127.0.0.1:9999";
      whisparrUrl = "http://127.0.0.1:6969";
      whisparrConfig = "/var/lib/whisparr/config.xml";
      hook = "${hook}/bin/nixflix-whisparr-import-hook";
      state = "/var/lib/nixflix-imports";
      inbox = "/var/lib/nixflix-imports-inbox";
      stashRoot = "/data";
      mediaRoot = "${config.nixflix.mediaDir}/porn";
      mount = config.fateflix.storage.root;
      requireMount = true;
      inherit (cfg) crf preset reserveBytes;
      commandTimeout = 21600;
      ffmpeg = "${pkgs.ffmpeg}/bin/ffmpeg";
      ffprobe = "${pkgs.ffmpeg}/bin/ffprobe";
    };
    systemd.tmpfiles.rules = [ "d /var/lib/nixflix-imports-inbox 0770 root media - -" ];
    systemd.services.nixflix-whisparr-policy = {
      description = "Prefer efficient Whisparr codecs and configure durable Stash intake";
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      after = [
        "whisparr.service"
        "network-online.target"
      ];
      unitConfig.ConditionPathExists = conditions;
      serviceConfig = common // {
        ExecStart = "${command}/bin/nixflix-imports reconcile";
        TimeoutStartSec = 180;
        InaccessiblePaths = [ config.fateflix.storage.root ];
      };
    };
    systemd.timers.nixflix-whisparr-policy = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2m";
        OnUnitInactiveSec = "5m";
      };
    };
    systemd.services.nixflix-import-ingest = {
      description = "Scan and identify new Whisparr imports without waiting for AV1 encoding";
      after = [
        "whisparr.service"
        "podman-stash.service"
      ];
      unitConfig.ConditionPathExists = conditions;
      serviceConfig = common // {
        ExecStart = "${command}/bin/nixflix-imports ingest";
        TimeoutStartSec = 1800;
        ReadWritePaths = [ "/var/lib/nixflix-imports-inbox" ];
        InaccessiblePaths = [ config.fateflix.storage.root ];
        MemoryMax = "256M";
      };
    };
    systemd.timers.nixflix-import-ingest = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "1m";
        OnUnitInactiveSec = "1m";
      };
    };
    systemd.services.nixflix-import-worker = {
      description = "Validate and replace one H.264 import with a 10-bit AV1 MP4";
      after = [
        "${utils.escapeSystemdPath config.fateflix.storage.root}.mount"
        "podman-stash.service"
        "whisparr.service"
      ];
      requires = [ "${utils.escapeSystemdPath config.fateflix.storage.root}.mount" ];
      unitConfig.ConditionPathExists = conditions;
      restartIfChanged = false;
      serviceConfig = common // {
        ExecStart = "${command}/bin/nixflix-imports run";
        TimeoutStartSec = "18h";
        TimeoutStopSec = 45;
        CPUQuota = cfg.cpuQuota;
        Nice = 15;
        CPUWeight = 10;
        IOWeight = 10;
        IOSchedulingClass = "idle";
        MemoryMax = "3G";
        MemorySwapMax = 0;
        ReadWritePaths = [ "${config.nixflix.mediaDir}/porn" ];
      };
    };
    systemd.timers.nixflix-import-worker = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2m";
        OnUnitInactiveSec = "1m";
      };
    };
  };
}
