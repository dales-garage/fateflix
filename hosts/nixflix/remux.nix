{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nixflixHost.remux;
  command = pkgs.writeShellScriptBin "nixflix-remux" ''
    exec ${pkgs.python3}/bin/python3 ${../../scripts/nixflix_remux.py} "$@"
  '';
in
{
  options.nixflixHost.remux = {
    enable = lib.mkEnableOption "the manually started, verified Stash AV1 remux queue" // {
      default = true;
    };
    reserveBytes = lib.mkOption {
      type = lib.types.ints.positive;
      default = 536870912000;
      description = "Minimum NAS free space retained while remuxing one file.";
    };
  };
  config = lib.mkIf (config.nixflixHost.production.enable && cfg.enable) {
    environment.systemPackages = [ command ];
    environment.etc."nixflix/remux.json".text = builtins.toJSON {
      url = "http://127.0.0.1:9999";
      stashRoot = "/data";
      mediaRoot = "/data/media/porn";
      mount = "/data";
      requireMount = true;
      inherit (cfg) reserveBytes;
      commandTimeout = 3600;
      ffmpeg = "${pkgs.ffmpeg}/bin/ffmpeg";
      ffprobe = "${pkgs.ffmpeg}/bin/ffprobe";
    };
    systemd.services.nixflix-remux = {
      description = "Resume the finite, verified Stash AV1-to-MP4 remux queue";
      # Creating a plan and starting it are explicit operator actions. No timer,
      # deployment trigger, or boot target starts media modification.
      requires = [ "data.mount" ];
      after = [
        "data.mount"
        "podman-stash.service"
      ];
      restartIfChanged = false;
      serviceConfig = {
        Type = "exec";
        ExecStart = "${command}/bin/nixflix-remux run";
        StateDirectory = "nixflix-remux";
        StateDirectoryMode = "0700";
        UMask = "0077";
        Restart = "no";
        TimeoutStopSec = 45;
        KillMode = "control-group";
        Nice = 15;
        CPUWeight = 10;
        IOWeight = 10;
        IOSchedulingClass = "idle";
        MemoryMax = "768M";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectHome = true;
        ProtectSystem = "strict";
        ReadWritePaths = [ "/data/media/porn" ];
      };
    };
  };
}
