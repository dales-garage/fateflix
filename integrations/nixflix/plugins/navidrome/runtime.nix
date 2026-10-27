{
  config,
  lib,
  options,
  pkgs,
  ...
}:
let
  modern = options.services.navidrome ? withPlugins;
  plugins =
    if modern then
      config.services.navidrome.withPlugins pkgs.pkgsCross.wasi32.navidromePlugins
    else
      [ ];
in
{
  # New Nixpkgs omits share/plugins for an empty selection. Its plugin engine
  # otherwise tries to create that directory in the read-only Nix store.
  config = lib.mkIf (config.nixflix.enable && config.nixflix.navidrome.enable && modern) {
    services.navidrome.settings.Plugins.Enabled = lib.mkDefault (plugins != [ ]);
  };
}
