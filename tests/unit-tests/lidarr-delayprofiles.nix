{ pkgs, lib, evalConfig, assertTest }:
let
  scriptFor =
    version:
    let
      evaluated = evalConfig [
        {
          nixflix = {
            enable = true;
            lidarr = {
              enable = true;
              package = pkgs.lidarr.overrideAttrs { inherit version; };
              config = {
                apiKey = "test-key";
                delayProfiles = [
                  {
                    id = 1;
                    preferredProtocol = "torrent";
                    torrentDelay = 360;
                  }
                ];
              };
            };
          };
        }
      ];
    in
    evaluated.config.systemd.services.lidarr-delayprofiles.script;
  legacy = scriptFor "3.1.0.4875";
  modern = scriptFor "3.1.6";
in
{
  lidarr-delayprofiles-legacy = assertTest "lidarr-delayprofiles-legacy" (
    lib.hasInfix ''"preferredProtocol":"torrent"'' legacy
    && lib.hasInfix ''"torrentDelay":360'' legacy
    && lib.hasInfix ''"enableUsenet":true'' legacy
    && !(lib.hasInfix ''"items":'' legacy)
  );
  lidarr-delayprofiles-modern = assertTest "lidarr-delayprofiles-modern" (
    lib.hasInfix ''"items":[{"allowed":true,"delay":360,"name":"Torrent","protocol":"TorrentDownloadProtocol"}'' modern
    && !(lib.hasInfix ''"preferredProtocol":'' modern)
    && !(lib.hasInfix ''"torrentDelay":'' modern)
  );
}
