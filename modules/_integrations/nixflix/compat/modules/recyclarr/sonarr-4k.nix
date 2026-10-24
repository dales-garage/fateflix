{ config, lib, ... }:
let
  cfg = config.nixflix.sonarr-4k;
in
{
  assertions = [
    {
      assertion = cfg.enable -> cfg.config.apiKey != null;
      message = "Recyclarr sonarr-4k sync requires an API key";
    }
  ];
  nixflix.recyclarr.config.sonarr.sonarr-4k = lib.mkIf cfg.enable {
    base_url = lib.mkDefault "http://${cfg.connectionAddress}:${toString cfg.config.hostConfig.port}${cfg.config.hostConfig.urlBase}";
    api_key = lib.mkDefault cfg.config.apiKey;
    delete_old_custom_formats = lib.mkDefault true;
    quality_definition.type = lib.mkDefault "series";
    quality_profiles = lib.mkDefault [
      {
        trash_id = "dfa5eaae7894077ad6449169b6eb03e0";
        reset_unmatched_scores.enabled = true;
      }
    ];
  };
}
