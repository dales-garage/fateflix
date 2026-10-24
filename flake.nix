{
  description = "Generic NixOS Jellyfin media server configuration with Arr stack";

  inputs = {
    comin = {
      url = "github:nlewo/comin";
      inputs.nixpkgs.follows = "nixpkgs-host";
      inputs.treefmt-nix.follows = "treefmt-nix";
    };
    trash-guides = {
      url = "github:TRaSH-Guides/Guides/56cb176ef4b59d734d3643287e66aafd7c809bd4";
      flake = false;
    };
    recyclarr-templates = {
      url = "github:recyclarr/config-templates/9faf65ff745d74ab906fd73cadaa25f08eb9d981";
      flake = false;
    };
    nixpkgs-host.url = "github:NixOS/nixpkgs/nixos-26.05";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    mkdocs-catppuccin = {
      url = "github:ruslanlap/mkdocs-catppuccin";
      flake = false;
    };
    vpn-confinement.url = "github:Maroka-chan/VPN-Confinement";
  };

  outputs =
    {
      self,
      nixpkgs,
      treefmt-nix,
      vpn-confinement,
      ...
    }@inputs:
    let
      inherit (nixpkgs) lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      perSystem =
        f:
        lib.genAttrs systems (
          system:
          f rec {
            inherit system lib;
            pkgs = import nixpkgs {
              inherit system;
              config.allowUnfree = true;
              config.allowUnfreePredicate = _: true;
              overlays = [ self.overlays.default ];
            };
            treefmt = treefmt-nix.lib.evalModule pkgs ./treefmt.nix;
          }
        );
    in
    {
      lib.buildJellyfinPlugin = { pkgs }: import ./lib/build-jellyfin-plugin.nix { inherit pkgs; };
      lib.jellyfinPlugins = import ./lib/jellyfin-plugins.nix { inherit lib; };

      overlays.default = import ./pkgs/overlay.nix;

      nixosModules.default = {
        imports = [
          (import ./modules)
          vpn-confinement.nixosModules.default
        ];
      };
      nixosModules.nixflix = self.nixosModules.default;

      nixosConfigurations.nixflix = inputs.nixpkgs-host.lib.nixosSystem {
        system = "x86_64-linux";
        specialArgs = { inherit inputs; };
        modules = [
          self.nixosModules.default
          ./hosts/nixflix
        ];
      };
      nixosConfigurations.nixflix-production = self.nixosConfigurations.nixflix.extendModules {
        modules = [ { nixflixHost.production.enable = true; } ];
      };
      nixosConfigurations.nixflix-staging = self.nixosConfigurations.nixflix.extendModules {
        modules = [ { nixflixHost.production.enable = lib.mkForce false; } ];
      };

      packages = perSystem (
        { system, pkgs, ... }:
        (import ./docs { inherit pkgs inputs; })
        // {
          default = self.packages.${system}.docs;
          inherit (pkgs) maintainerr notifiarr;
        }
      );

      apps = perSystem (
        { system, pkgs, ... }:
        {
          docs-serve = {
            type = "app";
            program = toString (
              pkgs.writeShellScript "docs-serve" ''
                echo "Starting documentation server from ${self.packages.${system}.docs}"
                ${pkgs.python3}/bin/python3 -m http.server --directory ${self.packages.${system}.docs} 8000
              ''
            );
          };
        }
        // import ./scripts/apps.nix { inherit pkgs self; }
      );

      formatter = perSystem ({ treefmt, ... }: treefmt.config.build.wrapper);

      checks = perSystem (
        {
          treefmt,
          lib,
          pkgs,
          system,
          ...
        }:
        let
          tests = import ./tests {
            inherit system pkgs lib;
            nixosModules = self.nixosModules.default;
          };
        in
        {
          formatting =
            assert lib.assertMsg (builtins.attrNames self.checks.${system} == import ./tests/check-names.nix)
              "CI check catalog does not match flake checks; update tests/check-names.nix and scripts/ci-plan.py together";
            treefmt.config.build.check self;
          gitops-eval = import ./tests/migration/gitops-eval.nix {
            inherit pkgs;
            host = self.nixosConfigurations.nixflix-production;
            staging = self.nixosConfigurations.nixflix-staging;
          };
          operations-eval = import ./tests/migration/operations-eval.nix {
            inherit pkgs;
            host = self.nixosConfigurations.nixflix-production;
          };
          remux-eval = import ./tests/migration/remux-eval.nix {
            inherit pkgs;
            host = self.nixosConfigurations.nixflix-production;
            staging = self.nixosConfigurations.nixflix-staging;
          };
          docs-build = self.packages.${system}.docs;
          four-instance-eval = import ./tests/migration/four-instance-eval.nix {
            inherit pkgs;
            host = self.nixosConfigurations.nixflix-staging;
            nixosModules = self.nixosModules.default;
          };
          production-eval = import ./tests/migration/production-eval.nix {
            inherit pkgs;
            host = self.nixosConfigurations.nixflix-production;
          };
          homepage-eval = import ./tests/migration/homepage-eval.nix {
            inherit pkgs;
            host = self.nixosConfigurations.nixflix-production;
            staging = self.nixosConfigurations.nixflix-staging;
            nixosModules = self.nixosModules.default;
          };
          notifiarr-eval = import ./tests/migration/notifiarr-eval.nix {
            inherit pkgs;
            host = self.nixosConfigurations.nixflix-production;
            staging = self.nixosConfigurations.nixflix-staging;
          };
        }
        // tests.vm-tests
        // {
          unit-tests = pkgs.linkFarmFromDrvs "unit-tests" (lib.attrValues tests.unit-tests);
        }
      );

      devShells = perSystem (
        { pkgs, treefmt, ... }: {
          default = pkgs.mkShell {
            nativeBuildInputs = [
              treefmt.config.build.wrapper
              pkgs.yarn-berry_4.yarn-berry-fetcher
              pkgs.jujutsu
              pkgs.git
              pkgs.openssh
              pkgs.rsync
              pkgs.jq
              (pkgs.python3.withPackages (p: [
                p.configobj
                p.pyyaml
              ]))
              pkgs.sqlite
              pkgs.curl
              pkgs.dnsutils
              pkgs.just
              pkgs.shellcheck
              pkgs.pass
              pkgs.gnupg
              pkgs.secretspec
              pkgs.skopeo
            ]
            ++ (lib.attrValues treefmt.config.build.programs);

            shellHook = ''
              echo "🎬 Nixflix Development Shell"
              echo ""
              echo "Documentation Commands:"
              echo "  nix build .#docs        - Build documentation"
              echo "  nix run .#docs-serve    - Serve docs"
              echo "  nix fmt                 - Format code"
              echo ""
            '';
          };
        }
      );
    };
}
