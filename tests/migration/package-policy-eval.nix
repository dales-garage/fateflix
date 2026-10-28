{ inputs, pkgs }:
let
  inherit (pkgs) lib;
  policy = import ../../lib/package-policy.nix { inherit lib; };
  normalize =
    value:
    (lib.evalModules {
      modules = [
        {
          options.packagePolicy = lib.mkOption {
            type = policy.type;
            default = { };
          };
        }
        { packagePolicy = value; }
      ];
    }).config.packagePolicy;
  defaults = normalize { };
  deny = normalize { unfree = "deny"; };
  allowlist = normalize {
    unfree = "allowlist";
    allowedNames = [ "policy-fixture" ];
  };
  evaluate = value: builtins.tryEval (builtins.deepSeq value true);
  packageSets =
    source: selected:
    import source {
      inherit (pkgs.stdenv.hostPlatform) system;
      config = policy.nixpkgsConfig selected;
    };
  fixture =
    packages: name: license:
    (packages.runCommand name { meta.license = license; } "touch $out").drvPath;
  accepts =
    packages: name: license:
    (evaluate (fixture packages name license)).success;
  composed =
    selected:
    inputs.flake-parts.lib.mkFlake { inherit inputs; } {
      imports = [ (inputs.import-tree ../../modules) ];
      fateflix.packagePolicy = selected;
      # Exercise the real perSystem package construction, not only the helper.
      perSystem = { pkgs, ... }: {
        packages.policy-fixture = pkgs.runCommand "policy-fixture-1.0" {
          meta.license = pkgs.lib.licenses.unfree;
        } "touch $out";
      };
    };
  restricted = composed { unfree = "deny"; };
  restrictedHost = restricted.nixosConfigurations.nixflix-production;
  allowed = composed {
    unfree = "allowlist";
    allowedNames = [ "plexmediaserver" ];
  };
  allowedTooling = composed {
    unfree = "allowlist";
    allowedNames = [ "policy-fixture" ];
  };
  toolingFixture = flake: flake.packages.${pkgs.stdenv.hostPlatform.system}.policy-fixture.drvPath;
  host = inputs.self.nixosConfigurations.nixflix-production;
in
assert defaults.unfree == "allow";
assert defaults.allowedNames == [ ];
assert
  !(evaluate (normalize {
    unfree = "sometimes";
  })).success;
assert
  !(evaluate (normalize {
    allowedNames = [ 42 ];
  })).success;
assert
  !(evaluate (normalize {
    allowedNames = [ "" ];
  })).success;
assert
  !(evaluate (normalize {
    unknownPolicy = true;
  })).success;
assert builtins.all
  (
    source:
    let
      unrestrictedPkgs = packageSets source defaults;
      deniedPkgs = packageSets source deny;
      allowlistedPkgs = packageSets source allowlist;
    in
    accepts unrestrictedPkgs "policy-fixture-1.0" lib.licenses.unfree
    && accepts deniedPkgs "free-fixture-1.0" lib.licenses.mit
    && !(accepts deniedPkgs "policy-fixture-1.0" lib.licenses.unfree)
    && accepts allowlistedPkgs "policy-fixture-1.0" lib.licenses.unfree
    && !(accepts allowlistedPkgs "other-fixture-1.0" lib.licenses.unfree)
  )
  [
    inputs.nixpkgs-host
    inputs.nixpkgs-media
    inputs.nixpkgs
  ];
assert host.pkgs.config.allowUnfree;
assert inputs.self.nixosConfigurations.nixflix-staging.pkgs.config.allowUnfree;
assert pkgs.config.allowUnfree;
assert !restrictedHost.pkgs.config.allowUnfree;
assert !restricted.nixosConfigurations.nixflix-staging.pkgs.config.allowUnfree;
assert !(evaluate (toolingFixture restricted)).success;
assert !(evaluate (toolingFixture allowed)).success;
assert (evaluate (toolingFixture allowedTooling)).success;
assert (evaluate (toolingFixture (composed { }))).success;
# Restricting licenses never changes the user's enabled capability selection.
assert restrictedHost.config.services.plex.enable;
assert !(evaluate restrictedHost.config.services.plex.package.drvPath).success;
assert
  (evaluate allowed.nixosConfigurations.nixflix-production.config.services.plex.package.drvPath)
  .success;
assert host.config.services.plex.enable;
assert (evaluate host.config.services.plex.package.drvPath).success;
pkgs.runCommand "package-policy-eval" { } "touch $out"
