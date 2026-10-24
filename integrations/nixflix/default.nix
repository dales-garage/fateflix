{ pkgs, src }:
let
  clean =
    path:
    pkgs.lib.cleanSourceWith {
      src = path;
      filter =
        file: _:
        !(builtins.elem (builtins.baseNameOf file) [
          "__pycache__"
          ".source-cache"
        ]);
    };
in
pkgs.applyPatches {
  name = "fateflix-nixflix-source";
  inherit src;
  patches = [
    ./patches/arr-runtime-credentials.patch
    ./patches/four-instance-integrations.patch
    ./patches/notification-reconciliation.patch
  ];
  postPatch = ''
    cp -R ${clean ./vendor/modules}/. modules/
    cp -R ${clean ./compatibility}/. modules/
    mkdir -p modules/jellyfin/plugins modules/navidrome/plugins
    cp -R ${clean ./plugins/jellyfin}/. modules/jellyfin/plugins/
    cp -R ${clean ./plugins/navidrome}/. modules/navidrome/plugins/
    cp -R ${clean ../../pkgs}/. pkgs/
    chmod -R u+w .
  '';
}
