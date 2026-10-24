{
  config,
  lib,
  pkgs,
  ...
}:
with lib;
let
  cfg = config.nixflix;
in
{

  config.services.caddy = mkIf (cfg.enable && cfg.caddy.enable) {
    enable = true;
    package = mkIf cfg.theme.enable (
      pkgs.caddy.withPlugins {
        plugins = [ "github.com/caddyserver/replace-response@v0.0.0-20250618171559-80962887e4c6" ];
        hash = "sha256-HgMECADAg5wqp/nOrWZg4HikpnRWU32VlyK7YJeWgjQ=";
      }
    );
    globalConfig = ''
      ${optionalString (cfg.caddy.tls.acmeEmail != null) "email ${cfg.caddy.tls.acmeEmail}"}
    '';
  };
}
