# Internal adapter shared by host composition, tests, and artifact generation.
{ inputs, source }:
{
  imports = [
    "${source}/modules"
    inputs.vpn-confinement.nixosModules.default
  ];
}
