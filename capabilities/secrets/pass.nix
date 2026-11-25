{ pkgs }:
# SecretSpec's pass provider uses the CLI protocol, not GPG directly.
pkgs.writeShellScriptBin "pass" ''
  exec ${pkgs.passage}/bin/passage "$@"
''
