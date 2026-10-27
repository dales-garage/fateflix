# Materialize local file-URL inputs before a read-only flake check. This copies
# source files directly; it introduces no build or import-from-derivation.
let
  directory = ../modules/_support/fixtures;
  names = builtins.readDir directory;
in
builtins.mapAttrs (name: _: builtins.path { path = directory + "/${name}"; }) (
  builtins.removeAttrs names (
    builtins.filter (name: names.${name} != "regular") (builtins.attrNames names)
  )
)
