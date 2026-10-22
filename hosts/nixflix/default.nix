{
  config,
  pkgs,
  modulesPath,
  ...
}:
{
  imports = [
    ./hardware-configuration.nix
    ./services.nix
    ./native-media.nix
    ./staging.nix
    ./production.nix
    ./gpu.nix
    ./remux.nix
    ./homepage.nix
    ./notifications.nix
    ./notifiarr.nix
    ./gitops.nix
    ./proxy.nix
    (modulesPath + "/virtualisation/xen-domU.nix")
  ];
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  networking.hostName = "nixflix";
  system.activationScripts.nixflix-hostname.text = "echo nixflix > /proc/sys/kernel/hostname";
  networking.networkmanager.enable = true;
  time.timeZone = "America/Chicago";
  i18n.defaultLocale = "en_US.UTF-8";
  system.stateVersion = "26.05";
  nixpkgs.config.allowUnfree = true;
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
    pass
    gnupg
    secretspec
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
  hardware.graphics = {
    enable = true;
    extraPackages = [
      pkgs.intel-media-driver
      pkgs.intel-vaapi-driver
    ];
  };
  nixflixHost.gpuPassthrough.enable = true;
  nixflixHost.production.enable = true;
  fileSystems."/data" = {
    device = "//10.69.0.10/data";
    fsType = "cifs";
    options = [
      "credentials=/var/lib/nixflix-secrets/current/smb"
      "vers=3.0"
      (if config.nixflixHost.production.enable then "rw" else "ro")
      "uid=0"
      "gid=169"
      "file_mode=0664"
      "dir_mode=0775"
      "nofail"
      "_netdev"
      "x-systemd.mount-timeout=30s"
    ];
  };
  systemd.tmpfiles.rules = [
    "d /var/lib/nixflix-migration 0700 root root -"
    "d /var/lib/nixflix-secrets 0700 root root -"
  ];
  system.activationScripts.nixflix-mountpoint.text = ''
    if ! ${pkgs.util-linux}/bin/mountpoint -q /data; then
      ${pkgs.coreutils}/bin/install -d -m 0000 -o root -g root /data
    fi
  '';
  # No credential values enter the store. The SMB client reads the persistent file.
  systemd.services.nixflix-nas-ready = {
    requires = [
      "data.mount"
      "nixflix-capacity-probe.service"
    ];
    after = [
      "data.mount"
      "nixflix-capacity-probe.service"
    ];
    bindsTo = [ "data.mount" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.python3}/bin/python3 ${../../scripts}/nixflix_ops.py nas-ready";
      TimeoutStartSec = 10;
    };
  };
}
