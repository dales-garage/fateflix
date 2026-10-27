{
  flake-file.inputs = {
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
    nixpkgs-media.url = "github:NixOS/nixpkgs/master";
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
      url = "github:kiriwalawren/nixflix";
      flake = false;
    };
  };
}
