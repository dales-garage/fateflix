{ config, lib, ... }:
let
  inherit (lib) mkOption types;
  containers = config.fateflix.containers;
  forBackend = backend: lib.filterAttrs (_: c: c.backend == backend) containers;
  legacy = forBackend "oci";
  quadlet = forBackend "quadlet";
  strings = mkOption {
    type = types.listOf types.str;
    default = [ ];
  };
in
{
  options.fateflix.containers = mkOption {
    description = "Podman containers owned by the FateFlix host.";
    default = { };
    type = types.attrsOf (
      types.submodule {
        options = {
          backend = mkOption {
            type = types.enum [
              "oci"
              "quadlet"
            ];
            default = "oci";
            description = "Systemd unit provider for this container.";
          };
          image = mkOption {
            type = types.str;
            description = "Fully qualified Podman image reference.";
          };
          environment = mkOption {
            type = types.attrsOf types.str;
            default = { };
            description = "Non-secret container environment.";
          };
          volumes = strings;
          ports = strings;
          extraOptions = strings;
        };
      }
    );
  };

  config = lib.mkIf (containers != { }) {
    assertions = lib.mapAttrsToList (name: _: {
      assertion = !(config.virtualisation.oci-containers.containers ? ${name});
      message = "FateFlix container ${name} cannot be declared in both Quadlet and oci-containers.";
    }) quadlet;

    virtualisation.podman.enable = true;
    virtualisation.oci-containers.backend = "podman";
    virtualisation.oci-containers.containers = lib.mapAttrs (_: c: {
      inherit (c)
        image
        environment
        volumes
        ports
        extraOptions
        ;
      autoStart = false;
    }) legacy;

    virtualisation.quadlet.containers = lib.mapAttrs' (
      name: c:
      lib.nameValuePair "podman-${name}" {
        # The NAS recovery unit starts containers only after its readiness checks.
        autoStart = false;
        containerConfig = {
          inherit name;
          inherit (c) image volumes;
          environments = c.environment;
          publishPorts = c.ports;
          podmanArgs = c.extraOptions;
          # Preserve the existing explicit cgroup parent for the Podman workload.
          cgroupsMode = "enabled";
        };
        serviceConfig = {
          Restart = "on-failure";
          TimeoutStartSec = "infinity";
        };
      }
    ) quadlet;
  };
}
