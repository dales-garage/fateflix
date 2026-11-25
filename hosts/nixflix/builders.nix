{ config, lib, ... }:
{
  # The operator must explicitly enable experimental nesting in XCP-ng first.
  # Loading the guest module alone cannot expose VT-x through Xen.
  config = lib.mkIf (config.fateflix.host.role == "production") {
    boot.kernelModules = [ "kvm-intel" ];
    users.users.marty.extraGroups = [ "kvm" ];
  };
}
