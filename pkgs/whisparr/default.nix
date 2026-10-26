{ whisparr_2, fetchurl }:
whisparr_2.overrideAttrs (
  final: previous: {
    version = "2.2.0-release.231";
    src = fetchurl {
      url = "https://github.com/Whisparr/Whisparr/releases/download/v${final.version}/Whisparr.${final.version}.linux-x64.tar.gz";
      hash = "sha256-0V6FIBYjZxZ6wm96Q/k3uli63VS6ytW/adra+bI8tI0=";
    };
    # The upstream Nix expression's recursive installPhase embeds its old version.
    installPhase = builtins.replaceStrings [ previous.version ] [ final.version ] previous.installPhase;
  }
)
