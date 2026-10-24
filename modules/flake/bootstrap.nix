{ inputs, lib, ... }: {
  imports = [
    inputs.flake-file.flakeModules.default
    inputs.den.flakeModules.default
  ];
  systems = [
    "x86_64-linux"
    "aarch64-linux"
  ];
  den.systems = [
    "x86_64-linux"
    "aarch64-linux"
  ];
  flake-file = {
    description = "FateFlix: modular media hosts downstream of NixFlix";
    outputs = "inputs: inputs.flake-parts.lib.mkFlake { inherit inputs; } (inputs.import-tree ./modules)";
  };
  den.schema.host.instantiate = lib.mkDefault (
    args:
    inputs.nixpkgs-host.lib.nixosSystem (
      args
      // {
        specialArgs = (args.specialArgs or { }) // {
          inherit inputs;
        };
      }
    )
  );
}
