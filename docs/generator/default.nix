{
  pkgs,
  lib,
  nixflixModule,
}:
let
  optionsGenerator = import ./generate-options.nix { inherit pkgs lib nixflixModule; };
in
{
  inherit (optionsGenerator) optionsDocs;
  inherit (optionsGenerator) optionsJSON;
  inherit (optionsGenerator) optionsCommonMark;
}
