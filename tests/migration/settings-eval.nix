{ inputs, pkgs }:
let
  configured = inputs.flake-parts.lib.mkFlake { inherit inputs; } {
    imports = [ (inputs.import-tree ../../modules) ];
    fateflix = {
      downloads.usenet.enable = pkgs.lib.mkForce false;
      playback.gpu.enable = pkgs.lib.mkForce false;
      imports.av1.enable = pkgs.lib.mkForce false;
      monitoring.notifiarr.enable = pkgs.lib.mkForce false;
      storage.mediaRoot = pkgs.lib.mkForce "/data/custom-media";
      storage.downloadsRoot = pkgs.lib.mkForce "/data/custom-downloads";
    };
  };
  cfg = configured.nixosConfigurations.nixflix-production.config;
  manifest = builtins.fromJSON cfg.environment.etc."nixflix/gitops-services.json".text;
in
assert !cfg.nixflix.usenetClients.sabnzbd.enable;
assert !cfg.services.sabnzbd.enable;
assert !cfg.nixflixHost.gpuPassthrough.enable;
assert !cfg.hardware.graphics.enable;
assert !cfg.nixflixHost.imports.enable;
assert !cfg.nixflixHost.remux.enable;
assert !cfg.nixflix.notifiarr.enable;
assert !(cfg.systemd.services ? notifiarr);
assert !(cfg.systemd.services ? nixflix-import-worker);
assert !(cfg.systemd.services ? nixflix-remux);
assert !(cfg.services.caddy.virtualHosts ? "http://sabnzbd.vm.internal");
assert !(manifest.services ? sabnzbd);
assert !manifest.monitoring.notifiarr;
assert cfg.nixflix.mediaDir == "/data/custom-media";
assert
  (builtins.fromJSON cfg.environment.etc."nixflix/operations.json".text).mediaRoot
  == "/data/custom-media";
assert cfg.nixflix.usenetClients.sabnzbd.downloadsDir == "/data/custom-downloads";
assert cfg.systemd.services.plex.serviceConfig.BindReadOnlyPaths == [ "/data/custom-media:/media" ];
assert builtins.all (a: a.assertion) cfg.assertions;
pkgs.runCommand "settings-eval" { } "touch $out"
