{
  # xen-domU disables timesyncd, but XCP-ng guests still need their own NTP
  # client. Use the native module (including its NetworkManager dispatcher)
  # and its standard networking.timeServers / services.chrony.servers options.
  services.chrony = {
    enable = true;
    # Never step the guest's clock, including on startup or a leap second.
    # NixOS enables makestep by default; Chrony otherwise corrects by slewing.
    makestep.enable = false;
    initstepslew.enabled = false;
    enableRTCTrimming = false;
    extraConfig = ''
      leapsecmode slew
    '';
  };
  services.ntp.enable = false;
}
