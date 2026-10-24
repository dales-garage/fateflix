{
  config,
  lib,
  pkgs,
  ...
}:
let
  staging = config.fateflix.host.role == "staging";
  manifest = if staging then ./secretspec-staging.toml else ./secretspec.toml;
in
{
  options.fateflix.secrets = {
    project = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      default = if staging then "nixflix-staging" else "nixflix";
    };
    manifest = lib.mkOption {
      type = lib.types.path;
      readOnly = true;
      default = manifest;
    };
    credentialDirectory = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      default = "/var/lib/nixflix-secrets/current";
    };
  };
  config = {
    environment.systemPackages = [
      pkgs.pass
      pkgs.gnupg
      pkgs.secretspec
    ];
    environment.etc."nixflix/secretspec.toml".source = manifest;
  };
}
