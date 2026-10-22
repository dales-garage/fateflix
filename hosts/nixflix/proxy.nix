{ config, lib, ... }:
let
  local = builtins.fromJSON (builtins.readFile ./local-services.json);
  routes = lib.concatLists (
    lib.mapAttrsToList (
      name: port:
      map
        (
          hostname:
          lib.nameValuePair "http://${hostname}" {
            extraConfig = "reverse_proxy http://127.0.0.1:${toString port}";
          }
        )
        (
          [
            "${name}.${local.domain}"
            name
          ]
          ++ lib.optional (builtins.elem name local.publicServices) "${
            local.publicNames.${name} or name
          }.dalebox.pw"
        )
    ) local.services
  );
in
{
  nixflix.caddy = {
    enable = true;
    domain = "dalebox.pw";
    tls.enable = false;
  };
  # Router Caddy terminates HTTPS. Keep HTTP origins for local fallback and the
  # existing Seerr tunnel, with public-domain aliases restricted by the manifest.
  services.caddy.virtualHosts = lib.mkForce (
    lib.listToAttrs (
      routes
      ++ [
        (lib.nameValuePair "http://seeme.dalebox.pw" {
          extraConfig = "reverse_proxy http://127.0.0.1:5055";
        })
      ]
    )
  );
  systemd.services.caddy = lib.mkIf (!config.nixflixHost.production.enable) {
    requires = [ "nixflix-staging-network.service" ];
    after = [ "nixflix-staging-network.service" ];
    serviceConfig.NetworkNamespacePath = "/run/netns/nixflix-staging";
  };
}
