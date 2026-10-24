{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nixflix.notifiarr;
  python = pkgs.python3.withPackages (p: [
    p.tomli-w
    p.pyyaml
  ]);
  specification = pkgs.writeText "notifiarr-settings.json" (
    builtins.toJSON (
      cfg.settings
      // {
        api_key = {
          _secret = cfg.apiKeyFile;
        };
        bind_addr = "${cfg.listenAddress}:${toString cfg.port}";
      }
    )
  );
in
{
  options.nixflix.notifiarr = {
    enable = lib.mkEnableOption "Notifiarr media integrations";
    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../../pkgs/notifiarr { };
      description = "Notifiarr client package.";
    };
    apiKeyFile = lib.mkOption {
      type = lib.types.str;
      description = "Absolute runtime path to the Notifiarr API key; never copied into the Nix store.";
    };
    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Address for the authenticated client UI and Plex webhooks.";
    };
    port = lib.mkOption {
      type = lib.types.port;
      default = 5454;
      description = "Notifiarr HTTP port.";
    };
    settings = lib.mkOption {
      inherit ((pkgs.formats.json { })) type;
      default = { };
      description = ''
        Declarative Notifiarr TOML settings. A value of { _secret = "/path"; }
        reads a secret at startup. Structured secret sources may additionally
        specify format (xml, json, yaml, ini) and a list-valued key path.
        GUI edits are replaced on restart. api_key and bind_addr are managed
        by apiKeyFile, listenAddress and port.
      '';
    };
  };
  config = lib.mkIf (config.nixflix.enable && cfg.enable) {
    assertions = [
      {
        assertion = lib.hasPrefix "/" cfg.apiKeyFile;
        message = "nixflix.notifiarr.apiKeyFile must be an absolute runtime path.";
      }
    ];
    systemd.services.notifiarr = {
      description = "Notifiarr media integration client";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      serviceConfig = {
        DynamicUser = true;
        StateDirectory = "notifiarr";
        StateDirectoryMode = "0700";
        RuntimeDirectory = "notifiarr";
        RuntimeDirectoryMode = "0700";
        WorkingDirectory = "/var/lib/notifiarr";
        ExecStartPre = "+${python}/bin/python3 ${./render.py} ${specification} /run/notifiarr/notifiarr.conf";
        ExecStart = "${lib.getExe cfg.package} --config /run/notifiarr/notifiarr.conf";
        Restart = "on-failure";
        RestartSec = 10;
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
      };
    };
  };
}
