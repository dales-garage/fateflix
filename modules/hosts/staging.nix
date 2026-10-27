{ den, ... }: {
  den.hosts.x86_64-linux.nixflix-staging.hostName = "nixflix";
  den.aspects.nixflix-staging = {
    includes = [ den.aspects.media-server ];
    nixos.fateflix.host.role = "staging";
  };

}
