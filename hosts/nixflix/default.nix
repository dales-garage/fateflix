{
  config,
  pkgs,
  modulesPath,
  ...
}:
{
  imports = [
    ./hardware-configuration.nix
    ./storage.nix
    ./network.nix
    ./time.nix
    ./maintenance.nix
    ./resources.nix
    (modulesPath + "/virtualisation/xen-domU.nix")
  ];
  config = {
    environment.etc."nixflix/mode".text = config.fateflix.host.role + "\n";
    boot.loader.systemd-boot.enable = true;
    boot.loader.efi.canTouchEfiVariables = true;
    networking.hostName = "nixflix";
    system.activationScripts.nixflix-hostname.text = "echo nixflix > /proc/sys/kernel/hostname";
    networking.networkmanager.enable = true;
    time.timeZone = "America/Chicago";
    i18n.defaultLocale = "en_US.UTF-8";
    system.stateVersion = "26.05";
    nix.settings.experimental-features = [
      "nix-command"
      "flakes"
    ];
    nix.settings.max-jobs = 1;
    nix.settings.cores = 2;
    environment.systemPackages = with pkgs; [
      jujutsu
      git
      rsync
      sqlite
      (python3.withPackages (p: [
        p.configobj
        p.pyyaml
      ]))
      curl
      jq
      cifs-utils
      iproute2
      socat
      libva-utils
      pciutils
    ];
    users.users.marty = {
      isNormalUser = true;
      extraGroups = [
        "wheel"
        "networkmanager"
        "media"
      ];
      openssh.authorizedKeys.keyFiles = [ ./administrator.pub ];
    };
    # marty key authentication and sudo were verified in a separate SSH session.
    security.sudo.extraRules = [
      {
        users = [ "marty" ];
        commands = [
          {
            command = "ALL";
            options = [ "NOPASSWD" ];
          }
        ];
      }
    ];
    services.openssh = {
      enable = true;
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
        PermitRootLogin = "no";
        AllowUsers = [ "marty" ];
      };
    };
    systemd.services.xen-guest-agent = {
      description = "Xen Guest Agent Daemon";
      wantedBy = [ "multi-user.target" ];
      after = [
        "local-fs.target"
        "network.target"
      ];
      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.xen-guest-agent}/bin/xen-guest-agent";
        Restart = "always";
        RestartSec = "5s";
      };
    };
  };
}
