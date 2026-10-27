{ inputs, pkgs }:
let
  inherit (pkgs) lib;
  configured = inputs.flake-parts.lib.mkFlake { inherit inputs; } (
    { den, ... }: {
      imports = [ (inputs.import-tree ../../modules) ];
      den.aspects.media-server.includes = lib.mkForce [
        den.aspects.fateflix-base
        den.aspects.storage
        den.aspects.secrets
        den.aspects.media
        den.aspects.downloads
        den.aspects.playback
      ];
      den.aspects.media-server.nixos.fateflix = {
        downloads.usenet.allowed = false;
        playback.acceleration = "software";
        storage.root = "/srv";
      };
    }
  );
  host = configured.nixosConfigurations.nixflix-production;
  cfg = host.config;
  staging = configured.nixosConfigurations.nixflix-staging.config;
  manifest = builtins.fromJSON cfg.environment.etc."nixflix/gitops-services.json".text;
  conflicts = map (module: (host.extendModules { modules = [ module ]; }).config) [
    { nixflix.mediaDir = lib.mkForce "/wrong"; }
    { nixflix.downloadsDir = lib.mkForce "/wrong"; }
    { nixflix.usenetClients.sabnzbd.downloadsDir = lib.mkForce "/wrong"; }
    { nixflix.usenetClients.sabnzbd.settings.misc.download_dir = lib.mkForce "/wrong"; }
    { nixflix.usenetClients.sabnzbd.settings.misc.complete_dir = lib.mkForce "/wrong"; }
  ];

in
assert !cfg.nixflix.usenetClients.sabnzbd.enable;
assert !cfg.services.sabnzbd.enable;
assert cfg.fateflix.playback.acceleration == "software";
assert !cfg.hardware.graphics.enable;
assert !cfg.nixflix.notifiarr.enable;
assert !(cfg.systemd.services ? notifiarr);
assert !(cfg.environment.etc ? "nixflix/freecore-notifiarr.py");
assert !(cfg.systemd.services ? nixflix-import-worker);
assert !(cfg.systemd.services ? nixflix-remux);
assert !(cfg.services.caddy.virtualHosts ? "http://sabnzbd.vm.internal");
assert !(manifest.services ? sabnzbd);
assert !manifest.monitoring.notifiarr;
assert cfg.nixflix.mediaDir == "/srv/media";
assert
  (builtins.fromJSON cfg.environment.etc."nixflix/operations.json".text).mediaRoot == "/srv/media";
assert cfg.nixflix.usenetClients.sabnzbd.downloadsDir == "/srv/usenet";
assert cfg.fateflix.downloads.incompleteDir == "/srv/usenet/intermediate";
assert cfg.fateflix.downloads.completedDir == "/srv/usenet/";
assert cfg.systemd.services.plex.serviceConfig.BindReadOnlyPaths == [ "/srv/media:/media" ];
assert !(staging.services ? comin);
assert staging.fateflix.storage.capacity.nas.warning == 1099511627776;
assert builtins.all (a: a.assertion) cfg.assertions;
assert builtins.all (a: a.assertion) staging.assertions;
assert host.options.fateflix.downloads.incompleteDir.default == "/srv/usenet/incomplete";
assert host.options.fateflix.downloads.completedDir.default == "/srv/usenet/complete";
assert cfg.fileSystems ? "/srv";
assert builtins.elem "srv.mount" cfg.systemd.services.nixflix-nas-ready.requires;
assert builtins.all (
  conflict: builtins.any (a: !a.assertion && lib.hasInfix "canonical" a.message) conflict.assertions
) conflicts;
pkgs.runCommand "settings-eval" { } "touch $out"
