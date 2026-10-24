{
  pkgs,
  host,
  staging,
}:
let
  inherit (pkgs) lib;
  disabled =
    (host.extendModules {
      modules = [
        {
          nixflix.torrentClients.qbittorrent.enable = true;
          nixflix.flaresolverr.enable = true;
          nixflix.downloadarr = lib.genAttrs [ "qbittorrent" "rtorrent" "deluge" "transmission" ] (_: {
            enable = true;
          });
          services.transmission.enable = true;
          nixflix.prowlarr.config.indexers = [
            { name = "Generic Torznab"; }
            { name = "Generic Newznab"; }
          ];
        }
      ];
    }).config;
  permitted =
    (host.extendModules {
      modules = [
        {
          fateflixPolicy.torrents = lib.mkForce true;
          nixflix.torrentClients.qbittorrent.enable = true;
        }
      ];
    }).config;
  noClients =
    (host.extendModules { modules = [ { fateflixPolicy.torrents = lib.mkForce true; } ]; }).config;
  software =
    (host.extendModules { modules = [ { nixflixHost.gpuPassthrough.enable = lib.mkForce false; } ]; })
    .config;
in
assert !disabled.services.qbittorrent.enable;
assert !disabled.services.transmission.enable;
assert !disabled.services.flaresolverr.enable;
assert builtins.all (name: !disabled.nixflix.downloadarr.${name}.enable) [
  "qbittorrent"
  "rtorrent"
  "deluge"
  "transmission"
];
assert map (i: i.name) disabled.nixflix.prowlarr.config.indexers == [ "Generic Newznab" ];
assert disabled.nixflix.prowlarr.config.indexerProxies == [ ];
assert builtins.all (p: !p.enableTorrent) disabled.nixflix.sonarr.config.delayProfiles;
assert permitted.services.qbittorrent.enable;
assert !permitted.services.transmission.enable;
assert !permitted.services.flaresolverr.enable;
assert !noClients.services.qbittorrent.enable;
assert builtins.all (p: p.enableTorrent) permitted.nixflix.sonarr.config.delayProfiles;
assert !(staging.config.systemd.services ? fateflix-download-policy);
assert software.services.plex.accelerationDevices == [ ];
pkgs.runCommand "torrent-policy-eval" { } "touch $out"
