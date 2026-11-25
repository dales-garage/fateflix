{ whisparr_2, fetchurl }:
whisparr_2.overrideAttrs (
  final: previous: {
    version = "2.3.0-release.455";
    src = fetchurl {
      url = "https://github.com/Whisparr/Whisparr/releases/download/v${final.version}/Whisparr.${final.version}.linux-x64.tar.gz";
      hash = "sha256-AoSOxUFgQT8CowXar/FqilnmQ7IISXk3I1W/dZ/Ji2I=";
    };
    # The upstream Nix expression's recursive installPhase embeds its old version.
    installPhase = builtins.replaceStrings [ previous.version ] [ final.version ] previous.installPhase;
  }
)
