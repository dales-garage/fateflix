{ config, lib, ... }:
let
  local = builtins.fromJSON (builtins.readFile ../../hosts/nixflix/local-services.json);
  cfg = config.fateflix.media.dashboard;
  homepage = config.nixflix.homepage;
  services = import ../../lib/media-services.nix { inherit lib local; };
  widgetServices = services.activeWidgets config;
  variable = name: lib.toUpper (lib.replaceStrings [ "-" ] [ "_" ] name);
  inherit (services) origin;
  card = name: label: description: {
    ${label} = {
      inherit description;
      icon = "${lib.removeSuffix "-4k" name}.svg";
      href =
        (
          if cfg.useInternalNames then
            "https://${name}.${local.domain}"
          else
            "http://${local.address}:${toString services.ports.${name}}"
        )
        + services.catalog.${name}.dashboardPath;
      siteMonitor = origin name + services.catalog.${name}.dashboardPath;
    }
    // lib.optionalAttrs (cfg.apiWidgets && builtins.elem name widgetServices) {
      widget = {
        type = lib.removeSuffix "-4k" name;
        url = origin name;
        key = "{{HOMEPAGE_FILE_${variable name}}}";
      };
    };
  };
in
{
  options.fateflix.media.dashboard = {
    apiWidgets = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Show Arr and SABnzbd metrics using the existing provisioned API keys.";
    };
    useInternalNames = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Link to internal HTTPS names. Set false for direct LAN IP links without the router CA.";
    };
    showAdultServices = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Include the Stash and Whisparr cards in a separate group.";
    };
  };

  config = {
    nixflix.homepage = {
      enable = lib.mkDefault (config.fateflix.host.role == "production");
      listenPort = services.ports.homepage;
      listenAddress = "0.0.0.0";
      # Router HTTPS and VM HTTP routes come from local-services.json.
      reverseProxy.expose = false;
      allowedHosts = [
        "homepage.${local.domain}"
        "homepage"
        "${local.address}:${toString homepage.listenPort}"
        "localhost:${toString homepage.listenPort}"
        "127.0.0.1:${toString homepage.listenPort}"
      ];
      apiKeyFiles = lib.optionalAttrs cfg.apiWidgets (
        lib.listToAttrs (
          map (
            name: lib.nameValuePair (variable name) "${config.fateflix.secrets.credentialDirectory}/${name}"
          ) widgetServices
        )
      );
      settings = {
        title = "Nixflix";
        description = "Media, requests and library management";
        theme = "dark";
        color = "slate";
        headerStyle = "clean";
        statusStyle = "dot";
        target = "_blank";
        hideVersion = true;
        layout =
          map
            (name: {
              ${name} = {
                style = "row";
                columns = 4;
              };
            })
            (
              [
                "Watch & Listen"
                "Movies & TV"
                "Downloads & Subtitles"
                "Books & Music"
              ]
              ++ lib.optional cfg.showAdultServices "Adult"
            );
      };
      services = [
        {
          "Watch & Listen" = [
            (card "plex" "Plex" "Movies and TV")
            (card "seerr" "Seerr" "Request movies and series")
            (card "audiobookshelf" "Audiobookshelf" "Audiobooks and podcasts")
            (card "tautulli" "Tautulli" "Plex activity and statistics")
          ];
        }
        {
          "Movies & TV" = [
            (card "sonarr" "Sonarr" "HD series")
            (card "sonarr-4k" "Sonarr 4K" "UHD series")
            (card "radarr" "Radarr" "HD movies")
            (card "radarr-4k" "Radarr 4K" "UHD movies")
          ];
        }
        {
          "Downloads & Subtitles" = [
            (card "prowlarr" "Prowlarr" "Search indexers")
          ]
          ++ lib.optional config.nixflix.usenetClients.sabnzbd.enable (
            card "sabnzbd" "SABnzbd" "Download queue"
          )
          ++ [
            (card "bazarr" "Bazarr" "HD subtitles")
            (card "bazarr-4k" "Bazarr 4K" "UHD subtitles")
          ];
        }
        {
          "Books & Music" = [
            (card "lidarr" "Lidarr" "Music library")
            (card "readarr" "Readarr" "Book library")
            (card "mylar3" "Mylar3" "Comics")
          ];
        }
      ]
      ++ lib.optional cfg.showAdultServices {
        Adult = [
          (card "stash" "Stash" "Media library")
          (card "whisparr" "Whisparr" "Library management")
        ];
      };
      widgets = [
        {
          resources = {
            cpu = true;
            memory = true;
            disk = "/";
          };
        }
        {
          datetime = {
            text_size = "lg";
            format = {
              dateStyle = "medium";
              timeStyle = "short";
              hour12 = true;
            };
          };
        }
      ];
      bookmarks = [
        {
          Guides = [
            {
              "TRaSH Guides" = [
                {
                  abbr = "TG";
                  href = "https://trash-guides.info/";
                }
              ];
            }
            {
              Recyclarr = [
                {
                  abbr = "RC";
                  href = "https://recyclarr.dev/";
                }
              ];
            }
            {
              Nixflix = [
                {
                  abbr = "NX";
                  href = "https://kiriwalawren.github.io/nixflix/";
                }
              ];
            }
          ];
        }
      ];
    };
  };
}
