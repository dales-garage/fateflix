{ lib, ... }:
let
  toggle =
    description: default:
    lib.mkOption {
      type = lib.types.bool;
      inherit default description;
    };
  absolutePath = lib.types.strMatching "/.*";
in
{
  options.fateflix = {
    downloads.usenet.enable = toggle "Enable the selected Usenet clients." true;
    downloads.torrents.enable = toggle "Permit individually selected torrent clients and integrations." false;
    playback.gpu.enable = toggle "Enable Intel GPU playback and diagnostics." true;
    imports.av1.enable = toggle "Enable the manual AV1 import and remux workers in production." true;
    monitoring.notifiarr.enable = toggle "Enable Notifiarr monitoring in production." true;
    storage.mediaRoot = lib.mkOption {
      type = absolutePath;
      default = "/data/media";
      description = "Media library root on the NAS.";
    };
    storage.downloadsRoot = lib.mkOption {
      type = absolutePath;
      default = "/data/usenet";
      description = "Usenet download root on the NAS.";
    };
  };
}
