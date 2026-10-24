{ config, lib, ... }:
let
  cfg = {
    torrents = config.fateflix.downloads.torrents.allowed;
    usenet = config.fateflix.downloads.usenet.allowed;
  };
  torrentClients = [
    "qbittorrent"
    "rtorrent"
    "deluge"
    "transmission"
  ];
in
{
  options.fateflix.downloads = {
    torrents.allowed = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Permit selected torrent clients and integrations.";
    };
    usenet.allowed = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Permit selected Usenet clients and integrations.";
    };
  };
  options.nixflix.downloadarr = lib.mkOption {
    apply =
      value:
      value
      // {
        extraClients =
          if cfg.torrents then
            value.extraClients
          else
            builtins.filter (
              client:
              lib.toLower (client.protocol or "") == "usenet"
              || builtins.elem (lib.toLower (client.implementationName or "")) [
                "sabnzbd"
                "nzbget"
              ]
            ) value.extraClients;
      };
  };
  options.nixflix.prowlarr.config.indexers = lib.mkOption {
    apply =
      indexers:
      if cfg.torrents then
        indexers
      else
        builtins.filter (
          indexer:
          lib.toLower (indexer.protocol or "") == "usenet"
          || lib.hasInfix "newznab" (lib.toLower indexer.schemaName)
        ) indexers;
  };
  config = lib.mkMerge [
    (lib.mkIf (!cfg.torrents) {
      nixflix.torrentClients.qbittorrent.enable = lib.mkForce false;
      nixflix.flaresolverr.enable = lib.mkForce false;
      nixflix.downloadarr =
        lib.genAttrs torrentClients (_: {
          enable = lib.mkForce false;
        })
        // { };
      nixflix.prowlarr.config.indexerProxies = lib.mkForce [ ];
      services =
        lib.genAttrs
          (
            torrentClients
            ++ [
              "flaresolverr"
              "autobrr"
              "cross-seed"
            ]
          )
          (_: {
            enable = lib.mkForce false;
          });
    })
    (lib.mkIf (!cfg.usenet) {
      nixflix.usenetClients.sabnzbd.enable = lib.mkForce false;
      nixflix.downloadarr.sabnzbd.enable = lib.mkForce false;
    })
  ];
}
