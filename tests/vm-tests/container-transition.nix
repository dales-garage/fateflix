{ pkgs, quadletModule, ... }:
let
  imageName = "localhost/fateflix-quadlet-fixture";
  image = pkgs.dockerTools.buildLayeredImage {
    name = imageName;
    tag = "test";
    config.Cmd = [
      "${pkgs.busybox}/bin/busybox"
      "httpd"
      "-f"
      "-p"
      "18181"
      "-h"
      "/state"
    ];
  };
  quadlet = {
    fateflix.containers.mylar3.backend = pkgs.lib.mkForce "quadlet";
  };
in
pkgs.testers.runNixOSTest {
  name = "fateflix-quadlet-transition";

  nodes.machine = {
    imports = [
      quadletModule
      ../../capabilities/media/containers.nix
    ];
    environment.systemPackages = [ pkgs.curl ];
    virtualisation.fileSystems."/srv/media" = {
      device = "tmpfs";
      fsType = "tmpfs";
      options = [ "noauto" ];
    };
    systemd.slices.nixflix-staging.sliceConfig.MemoryAccounting = true;
    systemd.services.podman-mylar3 = {
      after = [ "srv-media.mount" ];
      bindsTo = [ "srv-media.mount" ];
      unitConfig = {
        RequiresMountsFor = [ "/srv/media" ];
        ConditionPathExists = [
          "/var/lib/ready"
          "!/var/lib/hold"
        ];
      };
      serviceConfig.Slice = "nixflix-staging.slice";
    };
    fateflix.containers.mylar3 = {
      image = "${imageName}:test";
      volumes = [ "/var/lib/mylar3:/state:ro" ];
      extraOptions = [
        "--network=host"
        "--cgroup-parent=nixflix-staging.slice"
      ];
      environment.FATEFLIX_REVISION = "initial";
    };
    specialisation.quadlet.configuration = quadlet;
    specialisation.changed.configuration = {
      imports = [ quadlet ];
      fateflix.containers.mylar3.environment.FATEFLIX_REVISION = pkgs.lib.mkForce "updated";
    };
  };

  testScript = ''
    start_all()
    machine.succeed("podman load -i ${image}")
    machine.succeed("mkdir -p /var/lib/mylar3 && echo existing-state > /var/lib/mylar3/index.html")
    machine.succeed("touch /var/lib/ready && systemctl start podman-mylar3")
    machine.wait_until_succeeds("curl -fsS http://127.0.0.1:18181/ | grep -x existing-state")
    machine.fail("systemctl cat podman-mylar3 | grep -E 'SourcePath=.*/podman-mylar3[.]container$'")

    def switch(variant, recover=False):
        prefix = "/run/booted-system"
        if variant:
            prefix += f"/specialisation/{variant}"
        machine.succeed(f"{prefix}/bin/switch-to-configuration test")
        if recover:
            # A backend transition can stop on-demand units. Production
            # starts them again through the NAS recovery service.
            machine.succeed("systemctl start podman-mylar3")
        machine.wait_for_unit("podman-mylar3.service")
        machine.wait_until_succeeds("curl -fsS http://127.0.0.1:18181/ | grep -x existing-state")
        machine.succeed("test \"$(podman ps --format '{{.Names}}' | grep -xc mylar3)\" = 1")
        machine.succeed("systemctl show -p ControlGroup --value podman-mylar3 | grep -F /nixflix-staging.slice/")

    switch("quadlet", recover=True)
    machine.succeed("systemctl cat podman-mylar3 | grep -E 'SourcePath=.*/podman-mylar3[.]container$'")
    machine.succeed("podman inspect --format '{{range .Config.Env}}{{println .}}{{end}}' mylar3 | grep -x FATEFLIX_REVISION=initial")
    switch("changed")
    machine.succeed("podman inspect --format '{{range .Config.Env}}{{println .}}{{end}}' mylar3 | grep -x FATEFLIX_REVISION=updated")
    switch("", recover=True)
    machine.succeed("podman inspect --format '{{range .Config.Env}}{{println .}}{{end}}' mylar3 | grep -x FATEFLIX_REVISION=initial")

    switch("quadlet", recover=True)
    machine.succeed("systemctl stop srv-media.mount")
    machine.fail("systemctl is-active --quiet podman-mylar3")
    machine.succeed("systemctl mask --runtime srv-media.mount")
    machine.fail("systemctl start podman-mylar3")
    machine.succeed("systemctl unmask --runtime srv-media.mount && systemctl daemon-reload")
    machine.succeed("touch /var/lib/hold && systemctl start podman-mylar3")
    machine.fail("systemctl is-active --quiet podman-mylar3")
    machine.succeed("rm /var/lib/hold && systemctl start podman-mylar3")
    machine.wait_until_succeeds("curl -fsS http://127.0.0.1:18181/ | grep -x existing-state")
  '';
}
