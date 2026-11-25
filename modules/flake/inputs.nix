{
  flake-file.inputs = {
    comin = {
      url = "github:nlewo/comin";
      inputs.nixpkgs.follows = "nixpkgs-host";
      inputs.treefmt-nix.follows = "treefmt-nix";
    };
    trash-guides = {
      url = "github:TRaSH-Guides/Guides/83934a3e72b1950bffe14ca2ce743ce3de6b6b93";
      flake = false;
    };
    recyclarr-templates = {
      url = "github:recyclarr/config-templates/89eebadd429952069182a22930af4d768cacda36";
      flake = false;
    };
    nixpkgs-media.url = "github:NixOS/nixpkgs/master";
    quadlet-nix.url = "github:SEIAROTg/quadlet-nix";
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
    den.url = "github:denful/den";
    flake-file.url = "github:denful/flake-file";
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    import-tree.url = "github:vic/import-tree";
    nixflix = {
      url = "github:kiriwalawren/nixflix/main";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        treefmt-nix.follows = "treefmt-nix";
        mkdocs-catppuccin.follows = "mkdocs-catppuccin";
        vpn-confinement.follows = "vpn-confinement";
      };
    };
  };
}
