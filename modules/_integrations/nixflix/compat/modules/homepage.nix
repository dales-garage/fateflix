{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nixflix.homepage;
  yaml = pkgs.formats.yaml { };
  hostname = "${cfg.subdomain}.${config.nixflix.reverseProxy.domain}";
  inherit (import ../lib/mkVirtualHosts.nix { inherit lib config; }) mkVirtualHost;
in
{
  options.nixflix.homepage = {
    enable = lib.mkEnableOption "Homepage, the media stack dashboard";

    listenPort = lib.mkOption {
      type = lib.types.port;
      default = 8082;
      description = "Homepage HTTP port.";
    };

    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Bind address. Use a LAN address or 0.0.0.0 for direct access.";
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the Homepage port globally. Leave false when using LAN-specific firewall rules.";
    };

    subdomain = lib.mkOption {
      type = lib.types.str;
      default = "homepage";
      description = "Subdomain for the Nixflix reverse proxy.";
    };

    reverseProxy.expose = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Expose Homepage through the Nixflix reverse proxy. Enable only behind appropriate access controls.";
    };

    allowedHosts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "localhost:${toString cfg.listenPort}"
        "127.0.0.1:${toString cfg.listenPort}"
      ]
      ++ lib.optional cfg.reverseProxy.expose hostname;
      defaultText = lib.literalExpression ''[ "localhost:<port>" "127.0.0.1:<port>" ] ++ optional reverseProxy.expose "<subdomain>.<domain>"'';
      description = "Exact browser Host values, including ports for direct access. This is host validation, not authentication.";
    };

    apiKeyFiles = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      example = {
        SONARR = "/run/secrets/sonarr-api-key";
      };
      description = ''
        Runtime secret files loaded using systemd credentials, without copying
        their contents into the Nix store. Names must match [A-Z][A-Z0-9_]*.
        Reference SONARR in a widget with key = "{{HOMEPAGE_FILE_SONARR}}".
        Restart homepage-dashboard after rotating a key.
      '';
    };

    environmentFiles = lib.mkOption {
      type = lib.types.listOf lib.types.path;
      default = [ ];
      description = "Additional runtime environment files for Homepage variable substitution.";
    };

    settings = lib.mkOption {
      inherit (yaml) type;
      default = { };
      description = "Homepage settings.yaml, including title, theme and layout.";
    };

    services = lib.mkOption {
      inherit (yaml) type;
      default = [ ];
      description = "Grouped Homepage service cards, links, site monitors and API widgets.";
    };

    widgets = lib.mkOption {
      inherit (yaml) type;
      default = [ ];
      description = "Homepage information widgets, such as CPU, memory and disk usage.";
    };

    bookmarks = lib.mkOption {
      inherit (yaml) type;
      default = [ ];
      description = "Homepage bookmark groups.";
    };

    customCSS = lib.mkOption {
      type = lib.types.lines;
      default = "";
      description = "Additional Homepage CSS.";
    };
  };

  config = lib.mkIf (config.nixflix.enable && cfg.enable) (
    lib.mkMerge [
      (mkVirtualHost {
        inherit hostname;
        inherit (cfg.reverseProxy) expose;
        port = cfg.listenPort;
        upstreamHost = if cfg.listenAddress == "0.0.0.0" then "127.0.0.1" else cfg.listenAddress;
      })
      {
        assertions = lib.mapAttrsToList (name: path: {
          assertion = builtins.match "[A-Z][A-Z0-9_]*" name != null && lib.hasPrefix "/" path;
          message = "nixflix.homepage.apiKeyFiles requires uppercase variable names and absolute runtime paths.";
        }) cfg.apiKeyFiles;

        services.homepage-dashboard = {
          enable = true;
          inherit (cfg)
            listenPort
            openFirewall
            environmentFiles
            settings
            services
            widgets
            bookmarks
            customCSS
            ;
          allowedHosts = lib.concatStringsSep "," cfg.allowedHosts;
        };

        systemd.services.homepage-dashboard = {
          environment = {
            HOSTNAME = cfg.listenAddress;
          }
          // lib.mapAttrs' (name: _: lib.nameValuePair "HOMEPAGE_FILE_${name}" "%d/${name}") cfg.apiKeyFiles;
          serviceConfig.LoadCredential = lib.mapAttrsToList (name: path: "${name}:${path}") cfg.apiKeyFiles;
        };
      }
    ]
  );
}
