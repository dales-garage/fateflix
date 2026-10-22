# Keep the pure-Python planner's catalog aligned with exported flake checks.
# Listing filenames is lazy: this never evaluates any test derivations.
let
  names =
    directory: predicate:
    map (name: builtins.substring 0 (builtins.stringLength name - 4) name) (
      builtins.filter (name: (builtins.readDir directory).${name} == "regular" && predicate name) (
        builtins.attrNames (builtins.readDir directory)
      )
    );
in
builtins.sort builtins.lessThan (
  [
    "formatting"
    "docs-build"
    "unit-tests"
  ]
  ++ names ./vm-tests (name: name != "default.nix" && builtins.match ".*\\.nix" name != null)
  ++ names ./migration (name: builtins.match ".*-eval\\.nix" name != null)
)
