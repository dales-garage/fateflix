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
in
pkgs.testers.runNixOSTest {
  name = "fateflix-quadlet-activation";

  nodes.machine = {
    imports = [
      quadletModule
      ../../capabilities/media/containers.nix
    ];
    environment.systemPackages = [
      pkgs.curl
      pkgs.iproute2
    ];
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
    systemd.services.fateflix-test-netns = {
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        ${pkgs.iproute2}/bin/ip netns add fateflix-test
        ${pkgs.iproute2}/bin/ip -n fateflix-test link set lo up
      '';
    };
    systemd.services.podman-stash = {
      after = [ "fateflix-test-netns.service" ];
      requires = [ "fateflix-test-netns.service" ];
      serviceConfig.Slice = "nixflix-staging.slice";
    };
    systemd.services.podman-apprise = {
      unitConfig.ConditionPathExists = "/var/lib/apprise-credential";
      serviceConfig.Slice = "nixflix-staging.slice";
      preStart = ''
        ${pkgs.coreutils}/bin/install -D -m 0400 /var/lib/apprise-credential /run/apprise-state/index.html
      '';
    };
    fateflix.containers.stash = {
      image = "${imageName}:test";
      volumes = [ "/var/lib/mylar3:/state:ro" ];
      extraOptions = [
        "--network=ns:/run/netns/fateflix-test"
        "--cgroup-parent=nixflix-staging.slice"
      ];
    };
    fateflix.containers.apprise = {
      image = "${imageName}:test";
      volumes = [ "/run/apprise-state:/state:ro" ];
      ports = [ "127.0.0.1:18182:18181" ];
      extraOptions = [ "--cgroup-parent=nixflix-staging.slice" ];
    };
    specialisation.changed.configuration = {
      fateflix.containers.mylar3.environment.FATEFLIX_REVISION = pkgs.lib.mkForce "updated";
    };
  };

  testScript = ''
    start_all()
    machine.succeed("podman load -i ${image}")
    machine.succeed("mkdir -p /var/lib/mylar3 && echo existing-state > /var/lib/mylar3/index.html")
    machine.succeed("touch /var/lib/ready && systemctl start podman-mylar3")
    machine.wait_until_succeeds("curl -fsS http://127.0.0.1:18181/ | grep -x existing-state")
    machine.succeed("systemctl cat podman-mylar3 | grep -E 'SourcePath=/nix/store/.*/podman-mylar3[.]container$'")

    machine.succeed("systemctl start podman-stash")
    machine.wait_until_succeeds("ip netns exec fateflix-test curl -fsS http://127.0.0.1:18181/ | grep -x existing-state")
    machine.succeed("systemctl start podman-apprise")
    machine.fail("systemctl is-active --quiet podman-apprise")
    machine.succeed("echo fixture > /var/lib/apprise-credential && systemctl start podman-apprise")
    machine.wait_until_succeeds("curl -fsS http://127.0.0.1:18182/ | grep -x fixture")

    machine.succeed(
        "/run/booted-system/specialisation/changed/bin/switch-to-configuration test"
    )
    machine.wait_for_unit("podman-mylar3.service")
    machine.wait_until_succeeds("curl -fsS http://127.0.0.1:18181/ | grep -x existing-state")
    machine.succeed("test \"$(podman ps --format '{{.Names}}' | grep -xc mylar3)\" = 1")
    machine.succeed("systemctl show -p ControlGroup --value podman-mylar3 | grep -F /nixflix-staging.slice/")

    machine.wait_for_unit("podman-stash.service")
    machine.wait_for_unit("podman-apprise.service")
    machine.wait_until_succeeds(
        "ip netns exec fateflix-test curl -fsS http://127.0.0.1:18181/ | grep -x existing-state"
    )
    machine.wait_until_succeeds("curl -fsS http://127.0.0.1:18182/ | grep -x fixture")
    machine.succeed("podman port apprise 18181/tcp | grep -x 127.0.0.1:18182")

    machine.succeed("podman inspect --format '{{range .Config.Env}}{{println .}}{{end}}' mylar3 | grep -x FATEFLIX_REVISION=updated")

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
