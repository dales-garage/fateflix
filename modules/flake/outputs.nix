{ inputs, ... }: {
  perSystem =
    { system, ... }:
    let
      inherit (inputs) self;
      pkgs = import inputs.nixpkgs {
        inherit system;
        config.allowUnfree = true;
        overlays = [ self.overlays.default ];
      };
      treefmt = inputs.treefmt-nix.lib.evalModule pkgs ../../treefmt.nix;
      inherit (pkgs) lib;
    in
    {
      _module.args = { inherit pkgs treefmt; };
      packages =
        (import ../../docs {
          inherit pkgs inputs;
          nixflixModule = "${self.lib.nixflixSource}/modules";
        })
        // {
          default = self.packages.${system}.docs;
          inherit (pkgs) maintainerr notifiarr;
        };
      apps = {
        docs-serve = {
          type = "app";
          meta.description = "Serve the FateFlix documentation locally";
          program = toString (
            pkgs.writeShellScript "docs-serve" ''
              exec ${pkgs.python3}/bin/python3 -m http.server --directory ${self.packages.${system}.docs} 8000
            ''
          );
        };
      }
      // import ../../scripts/apps.nix { inherit pkgs self; };
      formatter = treefmt.config.build.wrapper;
      devShells.default = pkgs.mkShell {
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
          pkgs.ffmpeg
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
          echo "🎬 FateFlix Development Shell"
          echo ""
          echo "Documentation Commands:"
          echo "  nix build .#docs        - Build documentation"
          echo "  nix run .#docs-serve    - Serve docs"
          echo "  nix fmt                 - Format code"
          echo ""
        '';
      };
    };
}
