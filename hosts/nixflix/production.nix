{ config, lib, ... }:
let
  cfg = config.nixflixHost.production;
  lanNetworks = [
    "10.69.0.0/24"
    "10.42.0.0/24"
  ];
  localServices = builtins.fromJSON (builtins.readFile ./local-services.json);
  ports = lib.unique ([ 80 ] ++ builtins.attrValues localServices.services);
in
{
  options.nixflixHost.production.enable = lib.mkEnableOption "production media networking and NAS writes after cold cutover";
  config = lib.mkIf cfg.enable {
    # Keep globally routed IPv6 closed; the initial service audience is the LAN.
    networking.firewall.allowedTCPPorts = lib.mkForce [ 22 ];
    networking.firewall.extraCommands = ''
      # Dedicated Plex remote access; router forwards WAN TCP 32400 here.
      # IPv6 remains closed; other media apps are reached through router Caddy.
      iptables -A nixos-fw -p tcp --dport 32400 -j nixos-fw-accept
    ''
    + lib.concatMapStringsSep "\n" (
      network:
      lib.concatMapStringsSep "\n" (
        port: "iptables -A nixos-fw -s ${network} -p tcp --dport ${toString port} -j nixos-fw-accept"
      ) ports
    ) lanNetworks;
    environment.etc."nixflix/mode".text = "production\n";
  };
}
