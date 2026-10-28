# Evaluated before constructing any of the appliance's package sets.
{ lib }: {
  type = lib.types.submodule {
    options = {
      unfree = lib.mkOption {
        type = lib.types.enum [
          "allow"
          "deny"
          "allowlist"
        ];
        default = "allow";
        description = "Whether to permit all, none, or named unfree packages.";
      };
      allowedNames = lib.mkOption {
        type = lib.types.listOf lib.types.nonEmptyStr;
        default = [ ];
        example = [ "plexmediaserver" ];
        description = "Unversioned Nixpkgs package names permitted in allowlist mode.";
      };
    };
  };

  nixpkgsConfig = policy: {
    allowUnfree = policy.unfree == "allow";
    # Nixpkgs reports an evaluation error for denied packages. Do not turn
    # services off: an enabled service is a requirement, not a suggestion.
    allowUnfreePredicate =
      package:
      policy.unfree == "allow"
      || (policy.unfree == "allowlist" && lib.elem (lib.getName package) policy.allowedNames);
  };
}
