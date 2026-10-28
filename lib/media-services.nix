# Credential-free service identities shared by policy, monitoring and presentation.
# Ports retain the operator-facing manifest as their single source of truth.
{ lib, local }:
let
  arrOrder = [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "lidarr"
    "prowlarr"
    "readarr"
    "whisparr"
  ];
  nativeOrder = [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "lidarr"
    "prowlarr"
    "sabnzbd"
    "plex"
    "seerr"
    "bazarr"
    "bazarr-4k"
    "tautulli"
    "audiobookshelf"
    "readarr"
    "whisparr"
  ];
  widgetNames = [
    "sonarr"
    "sonarr-4k"
    "radarr"
    "radarr-4k"
    "prowlarr"
    "lidarr"
    "sabnzbd"
  ];
  serviceType = lib.types.submodule (
    { name, ... }: {
      options = {
        port = lib.mkOption { type = lib.types.ints.between 1 65535; };
        unit = lib.mkOption {
          type = lib.types.nonEmptyStr;
          default = name;
        };
        apiVersion = lib.mkOption {
          type = lib.types.nullOr (
            lib.types.enum [
              "v1"
              "v3"
            ]
          );
          default = null;
        };
        aliasOf = lib.mkOption {
          type = lib.types.nullOr lib.types.nonEmptyStr;
          default = null;
        };
        healthPath = lib.mkOption {
          type = lib.types.strMatching "/.*";
          default = "/";
        };
        dashboardPath = lib.mkOption {
          type = lib.types.strMatching "/.*";
          default = "/";
        };
        widget = lib.mkOption {
          type = lib.types.bool;
          default = lib.elem name widgetNames;
        };
      };
    }
  );
  catalog =
    (lib.evalModules {
      modules = [
        { options.services = lib.mkOption { type = lib.types.attrsOf serviceType; }; }
        {
          services = lib.mapAttrs (
            name: port:
            {
              inherit port;
              apiVersion =
                if lib.elem name arrOrder then
                  (
                    if
                      lib.elem name [
                        "lidarr"
                        "prowlarr"
                        "readarr"
                      ]
                    then
                      "v1"
                    else
                      "v3"
                  )
                else
                  null;
            }
            // lib.optionalAttrs (name == "homepage") { unit = "homepage-dashboard"; }
            // lib.optionalAttrs (lib.elem name [
              "mylar3"
              "stash"
            ]) { unit = "podman-${name}"; }
            // lib.optionalAttrs (name == "seeme") {
              aliasOf = "seerr";
              unit = "seerr";
            }
            // lib.optionalAttrs (name == "plex") { dashboardPath = "/web/"; }
          ) local.services;
        }
      ];
    }).config.services;
  enabled =
    config: name:
    (config.nixflix.${name}.enable or false)
    || (config.services.${name}.enable or false)
    || (name == "sabnzbd" && (config.nixflix.usenetClients.sabnzbd.enable or false))
    || (name == "bazarr-4k" && (config.users.users or { }) ? bazarr-4k);
  # Preserve the existing route contract: only SABnzbd is conditionally exposed.
  # Aliases and non-Arr services remain present exactly as in local-services.json.
  routed =
    config:
    lib.filterAttrs (
      name: _: name != "sabnzbd" || (config.nixflix.usenetClients.sabnzbd.enable or false)
    ) catalog;
in
assert lib.assertMsg (builtins.all
  (
    name:
    let
      service = catalog.${name};
    in
    service.aliasOf == null
    || (catalog ? ${service.aliasOf} && service.port == catalog.${service.aliasOf}.port)
  )
  (builtins.attrNames catalog)
) "Media service aliases must refer to an existing service with the same port";
builtins.deepSeq catalog {
  inherit
    catalog
    enabled
    routed
    serviceType
    ;
  ports = lib.mapAttrs (_: service: service.port) catalog;
  origin = name: "http://127.0.0.1:${toString catalog.${name}.port}";
  activeArr = config: lib.filter (enabled config) arrOrder;
  activeNative = config: lib.filter (enabled config) nativeOrder;
  activeWidgets =
    config:
    lib.filter (
      name:
      catalog.${name}.widget
      && (name != "sabnzbd" || (config.nixflix.usenetClients.sabnzbd.enable or false))
    ) (builtins.attrNames catalog);
  proxyPorts = config: lib.mapAttrs (_: service: service.port) (routed config);
  health =
    config:
    lib.mapAttrs (_: service: {
      inherit (service)
        unit
        apiVersion
        healthPath
        aliasOf
        ;
    }) (routed config);
}
