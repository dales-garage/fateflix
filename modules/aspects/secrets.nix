{
  den.aspects.secrets.nixos = { pkgs, ... }: {
    # SecretSpec provisioning remains an explicit operator action. Persistent
    # credentials are referenced at runtime and never imported into the store.
    environment.systemPackages = [
      pkgs.pass
      pkgs.gnupg
      pkgs.secretspec
    ];
  };
}
