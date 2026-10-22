#!/usr/bin/env python3
"""Exercise missing-credential and missing-NAS behavior on the staging VM only."""

from pathlib import Path
import argparse
import os
import subprocess

NATIVE = [
    "sonarr",
    "sonarr-4k",
    "radarr",
    "radarr-4k",
    "lidarr",
    "prowlarr",
    "sabnzbd",
    "plex",
    "seerr",
    "bazarr",
    "bazarr-4k",
    "tautulli",
    "audiobookshelf",
    "readarr",
    "whisparr",
]
CONTAINERS = [
    "podman-" + n
    for n in [
        "mylar3",
        "apprise",
        "stash",
    ]
]


def systemctl(*args, check=True):
    return subprocess.run(
        ["systemctl", *args],
        check=check,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    if os.geteuid() != 0 or Path("/etc/hostname").read_text().strip() != "nixflix":
        raise RuntimeError("Run as root on nixflix only")
    if (
        Path("/etc/nixflix/mode").exists()
        and Path("/etc/nixflix/mode").read_text().strip() == "production"
    ):
        raise RuntimeError("Isolation test is only valid before production activation")
    route = subprocess.check_output(["ip", "-n", "nixflix-staging", "route"], text=True)
    if route.strip():
        raise RuntimeError("Staging namespace unexpectedly has a route")
    recovery_timer = "nixflix-nas-recover.timer"
    recovery_active = (
        systemctl("is-active", "--quiet", recovery_timer, check=False).returncode == 0
    )
    running = [
        s
        for s in NATIVE + CONTAINERS
        if systemctl("is-active", "--quiet", s, check=False).returncode == 0
    ]
    dropin = Path("/run/systemd/system/sonarr.service.d/99-missing-secret-test.conf")
    if dropin.exists():
        raise RuntimeError("A previous test drop-in exists; inspect it first")
    systemctl("stop", "sonarr")
    try:
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(
            "[Service]\nLoadCredential=\nLoadCredential=apiKey:/run/nixflix-deliberately-missing\n"
        )
        systemctl("daemon-reload")
        if systemctl("start", "sonarr", check=False).returncode == 0:
            raise RuntimeError("Sonarr started with a missing credential")
        print("PASS: missing credential prevents startup", flush=True)
    finally:
        dropin.unlink(missing_ok=True)
        systemctl("daemon-reload")
        systemctl("reset-failed", "sonarr", check=False)
    try:
        systemctl("stop", recovery_timer, "nixflix-nas-recover.service")
        systemctl("stop", "data.mount")
        systemctl("mask", "--runtime", "data.mount")
        if systemctl("start", "sonarr", check=False).returncode == 0:
            raise RuntimeError("Sonarr started without the NAS")
        if any(
            systemctl("is-active", "--quiet", s, check=False).returncode == 0
            for s in NATIVE + CONTAINERS
        ):
            raise RuntimeError(
                "A media service survived loss of its required NAS mount"
            )
        if list(Path("/data").iterdir()):
            raise RuntimeError("Unexpected files in the unmounted local directory")
        if (
            subprocess.run(
                ["runuser", "-u", "sonarr", "--", "test", "-w", "/data"]
            ).returncode
            == 0
        ):
            raise RuntimeError("The service user can write to unmounted /data")
        print(
            "PASS: NAS loss stops services and prevents local fallback writes",
            flush=True,
        )
    finally:
        systemctl("unmask", "--runtime", "data.mount")
        systemctl("daemon-reload")
        systemctl("reset-failed", check=False)
        systemctl("start", "data.mount")
        if running:
            systemctl("start", *running)
        if recovery_active:
            systemctl("start", recovery_timer)
    print("Restored the previously running staged services", flush=True)


if __name__ == "__main__":
    main()
