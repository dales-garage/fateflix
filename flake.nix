# DO-NOT-EDIT. This file was auto-generated using github:denful/flake-file.
# Use `nix run .#write-flake` to regenerate it.
{
  description = "FateFlix: modular media hosts downstream of NixFlix";

  outputs = inputs: inputs.flake-parts.lib.mkFlake { inherit inputs; } (inputs.import-tree ./modules);

  inputs = {
    comin = {
      url = "github:nlewo/comin";
      inputs = {
        nixpkgs.follows = "nixpkgs-host";
        treefmt-nix.follows = "treefmt-nix";
      };
    };
    den.url = "github:denful/den";
    flake-file.url = "github:denful/flake-file";
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    import-tree.url = "github:vic/import-tree";
    mkdocs-catppuccin = {
      url = "github:ruslanlap/mkdocs-catppuccin";
      flake = false;
    };
    nixflix = {
      url = "github:kiriwalawren/nixflix";
      flake = false;
    };
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixpkgs-host.url = "github:NixOS/nixpkgs/nixos-26.05";
    nixpkgs-media.url = "github:NixOS/nixpkgs/master";
    recyclarr-templates = {
      url = "github:recyclarr/config-templates/9faf65ff745d74ab906fd73cadaa25f08eb9d981";
      flake = false;
    };
    trash-guides = {
      url = "github:TRaSH-Guides/Guides/56cb176ef4b59d734d3643287e66aafd7c809bd4";
      flake = false;
    };
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    vpn-confinement.url = "github:Maroka-chan/VPN-Confinement";
  };
}
