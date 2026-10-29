{ inputs, ... }: {
  perSystem =
    {
      pkgs,
      system,
      lib,
      treefmt,
      ...
    }:
    let
      inherit (inputs) self;
      tests = import ../../tests {
        inherit system pkgs lib;
        nixosModules = self.nixosModules.default;
        nixflixSource = self.lib.nixflixSource;
      };
    in
    {
      checks = {
        formatting =
          assert lib.assertMsg
            (builtins.attrNames self.checks.${system} == import ../../tests/check-names.nix)
            "CI check catalog does not match flake checks; update tests/check-names.nix and scripts/ci-plan.py together";
          treefmt.config.build.check self;
        package-policy-eval = import ../../tests/migration/package-policy-eval.nix { inherit inputs pkgs; };
        service-catalog-eval = import ../../tests/migration/service-catalog-eval.nix {
          inherit inputs pkgs;
        };
        capabilities-eval = import ../../tests/migration/capabilities-eval.nix { inherit inputs pkgs; };
        settings-eval = import ../../tests/migration/settings-eval.nix { inherit inputs pkgs; };
        resources-eval = import ../../tests/migration/resources-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-production;
          staging = self.nixosConfigurations.nixflix-staging;
        };
        torrent-policy-eval = import ../../tests/migration/torrent-policy-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-production;
          staging = self.nixosConfigurations.nixflix-staging;
        };
        gitops-eval = import ../../tests/migration/gitops-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-production;
          staging = self.nixosConfigurations.nixflix-staging;
        };
        operations-eval = import ../../tests/migration/operations-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-production;
          staging = self.nixosConfigurations.nixflix-staging;
        };
        remux-eval = import ../../tests/migration/remux-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-production;
          staging = self.nixosConfigurations.nixflix-staging;
        };
        docs-build = self.packages.${system}.docs;
        four-instance-eval = import ../../tests/migration/four-instance-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-staging;
          nixosModules = self.nixosModules.default;
        };
        production-eval = import ../../tests/migration/production-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-production;
        };
        homepage-eval = import ../../tests/migration/homepage-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-production;
          staging = self.nixosConfigurations.nixflix-staging;
          nixosModules = self.nixosModules.default;
        };
        notifiarr-eval = import ../../tests/migration/notifiarr-eval.nix {
          inherit pkgs;
          host = self.nixosConfigurations.nixflix-production;
          staging = self.nixosConfigurations.nixflix-staging;
        };
      }
      // tests.vm-tests
      // {
        unit-tests = pkgs.linkFarmFromDrvs "unit-tests" (lib.attrValues tests.unit-tests);
      };
    };
}
