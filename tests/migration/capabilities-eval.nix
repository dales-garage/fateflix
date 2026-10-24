{ pkgs, inputs }:
let
  inherit (inputs) self;
  prod = self.nixosConfigurations.nixflix-production;
  staging = self.nixosConfigurations.nixflix-staging;
  cfg = staging.config;
  secretManifest = builtins.fromTOML (builtins.readFile cfg.fateflix.secrets.manifest);
  productionManifest = builtins.fromTOML (builtins.readFile prod.config.fateflix.secrets.manifest);
in
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
pkgs.runCommand "capabilities-eval" { } "touch $out"
