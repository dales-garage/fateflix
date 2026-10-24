{ pkgs, inputs }:
let
  inherit (inputs) self;
  prod = self.nixosConfigurations.nixflix-production;
  staging = self.nixosConfigurations.nixflix-staging;
  cfg = staging.config;
  # Exercise real aspect composition without the shared profile, deployment,
  # machine hardware, or an accidental media import supplying declarations.
  isolated =
    aspect: extra:
    let
      composed = inputs.flake-parts.lib.mkFlake { inherit inputs; } (
        { den, lib, ... }: {
          imports = [ (inputs.import-tree ../../modules) ];
          den.aspects.nixflix-production = {
            includes = lib.mkForce [ den.aspects.${aspect} ];
            nixos = extra // {
              fileSystems."/" = {
                device = "/dev/null";
                fsType = "ext4";
              };
              boot.loader.grub.device = "/dev/null";
              system.stateVersion = "26.05";
            };
          };
        }
      );
    in
    composed.nixosConfigurations.nixflix-production.config;
  freecore = isolated "freecore" { };
  monitoring = isolated "monitoring" { };
  downloads = isolated "downloads" { };
  playback = isolated "playback" { fateflix.playback.acceleration = "software"; };

  secretManifest = builtins.fromTOML (builtins.readFile cfg.fateflix.secrets.manifest);
  productionManifest = builtins.fromTOML (builtins.readFile prod.config.fateflix.secrets.manifest);
in
assert
  self.nixosConfigurations.fateflix.config.system.build.toplevel.drvPath
  == prod.config.system.build.toplevel.drvPath;
assert
  self.nixosConfigurations.nixflix.config.system.build.toplevel.drvPath
  == prod.config.system.build.toplevel.drvPath;
assert !(cfg.services ? comin);
assert builtins.all (name: !(cfg.systemd.services ? ${name})) [
  "comin"
  "nixflix-health"
  "nixflix-health-endpoint"
  "nixflix-playback"
  "notifiarr"
  "podman-apprise"
  "notifiarr-connections"
];
assert builtins.all (name: !(cfg.environment.etc ? ${name})) [
  "nixflix/gitops-services.json"
  "nixflix/imports.json"
  "nixflix/remux.json"
];
assert cfg.fateflix.secrets.project == "nixflix-staging";
assert secretManifest.project.name == "nixflix-staging";
assert builtins.attrNames secretManifest.profiles == [ "default" ];
assert
  builtins.attrNames secretManifest.profiles.default
  == builtins.attrNames productionManifest.profiles.default;
assert productionManifest.project.name == "nixflix";
assert prod.config.fateflix.secrets.credentialDirectory == cfg.fateflix.secrets.credentialDirectory;
assert cfg.fateflix.storage.capacity.probeMaxAge == 180;
assert cfg.users.users.nixflix-apprise.uid == prod.config.users.users.nixflix-apprise.uid;
assert cfg.users.groups.nixflix-apprise.gid == prod.config.users.groups.nixflix-apprise.gid;
assert prod.config.fateflix.downloads.incompleteDir == "/data/usenet/intermediate";
assert prod.config.fateflix.downloads.completedDir == "/data/usenet/";
assert builtins.all (a: a.assertion) cfg.assertions;
assert freecore.environment.etc ? "nixflix/freecore-notifiarr.py";
assert !freecore.nixflix.notifiarr.enable;
assert !(freecore.systemd.services ? notifiarr);
assert !(freecore.systemd.services ? plex);
assert !(freecore.services ? comin);
assert monitoring.nixflix.notifiarr.enable;
assert !(monitoring.environment.etc ? "nixflix/freecore-notifiarr.py");
assert builtins.all (
  check: !(pkgs.lib.hasPrefix "FreeCORE " check.name)
) monitoring.nixflix.notifiarr.settings.service;
assert !downloads.services.plex.enable;
assert downloads.nixflix.usenetClients.sabnzbd.enable;
assert downloads.fateflix.downloads.incompleteDir == "/data/usenet/incomplete";
assert downloads.fateflix.secrets.project == "nixflix";
assert !(downloads.systemd.services ? bazarr-4k);
assert !(downloads.systemd.services ? recyclarr);
assert playback.services.plex.enable;
assert !playback.hardware.graphics.enable;
assert playback.fateflix.storage.mediaRoot == "/data/media";
assert playback.fateflix.secrets.project == "nixflix";
assert !playback.fateflix.downloads.torrents.allowed;
assert !(playback.environment.etc ? "nixflix/freecore-notifiarr.py");
assert !(playback.systemd.services ? nixflix-remux);
assert !(playback.services ? comin);
assert builtins.all (a: a.assertion) freecore.assertions;
assert builtins.all (a: a.assertion) monitoring.assertions;
assert builtins.all (a: a.assertion) downloads.assertions;
assert builtins.all (a: a.assertion) playback.assertions;
pkgs.runCommand "capabilities-eval" { } "touch $out"
