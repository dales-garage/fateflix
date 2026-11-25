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
      url = "github:kiriwalawren/nixflix/main";
      inputs = {
        mkdocs-catppuccin.follows = "mkdocs-catppuccin";
        nixpkgs.follows = "nixpkgs";
        treefmt-nix.follows = "treefmt-nix";
        vpn-confinement.follows = "vpn-confinement";
      };
    };
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixpkgs-host.url = "github:NixOS/nixpkgs/nixos-26.05";
    nixpkgs-media.url = "github:NixOS/nixpkgs/master";
    quadlet-nix.url = "github:SEIAROTg/quadlet-nix";
    recyclarr-templates = {
      url = "github:recyclarr/config-templates/89eebadd429952069182a22930af4d768cacda36";
      flake = false;
    };
    trash-guides = {
      url = "github:TRaSH-Guides/Guides/83934a3e72b1950bffe14ca2ce743ce3de6b6b93";
      flake = false;
    };
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    vpn-confinement.url = "github:Maroka-chan/VPN-Confinement";
  };
}
