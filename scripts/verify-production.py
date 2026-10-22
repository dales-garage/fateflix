#!/usr/bin/env python3
"""Verify production services, private credentials, NAS writes, and Plex entitlement.

Run as root on nixflix. The only NAS mutation is a temporary empty probe file,
removed immediately, in each managed download category. No media is moved.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

PORTS = {
    "sonarr": 8990,
    "sonarr-4k": 8989,
    "radarr": 7879,
    "radarr-4k": 7878,
    "lidarr": 8686,
    "prowlarr": 9696,
    "sabnzbd": 8080,
    "plex": 32400,
    "seerr": 5055,
    "bazarr": 6767,
    "bazarr-4k": 6777,
    "tautulli": 8181,
    "audiobookshelf": 13378,
    "readarr": 8787,
    "whisparr": 6969,
    "podman-mylar3": 8090,
    "podman-stash": 9999,
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if os.geteuid() != 0 or socket.gethostname() != "nixflix":
        p.error("run as root on nixflix")
    if Path("/etc/nixflix/mode").read_text().strip() != "production":
        p.error("host is not in production mode")
    os.umask(0o077)
    report = {
        "checked": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "system": os.readlink("/run/current-system"),
        "services": {},
    }
    mount = json.loads(
        subprocess.check_output(
            ["findmnt", "--json", "--mountpoint", "/data", "-o", "FSTYPE,OPTIONS"]
        )
    )["filesystems"][0]
    if mount["fstype"] != "cifs" or "rw" not in mount["options"].split(","):
        raise RuntimeError("NAS must be a writable CIFS mount")
    report["nas"] = {"type": "cifs", "writable": True}
    for name, port in PORTS.items():
        subprocess.run(["systemctl", "is-active", "--quiet", name], check=True)
        try:
            with urlopen(f"http://127.0.0.1:{port}", timeout=20) as response:
                code = response.status
        except HTTPError as error:
            code = error.code
        if code not in (200, 401, 403):
            raise RuntimeError(name + " has unexpected HTTP status " + str(code))
        report["services"][name] = {"active": True, "http": code}
    for name in ("sonarr", "sonarr-4k", "radarr", "radarr-4k", "lidarr"):
        subprocess.run(
            [
                "runuser",
                "-u",
                name,
                "--",
                sys.executable,
                "-c",
                "import os,tempfile; fd,p=tempfile.mkstemp(prefix='.nixflix-write-probe-',dir="
                + repr("/data/usenet/" + name)
                + "); os.close(fd); os.unlink(p)",
            ],
            check=True,
        )
    report["category_write_probes"] = "passed"
    for file in Path("/var/lib/nixflix-secrets/current").iterdir():
        st = file.stat()
        if st.st_uid != 0 or st.st_mode & 0o077:
            raise RuntimeError("Credential ownership/permissions failed")
    report["credentials"] = "root-owned private files"
    prefs = ET.parse("/var/lib/plex/Plex Media Server/Preferences.xml").getroot()
    headers = {
        "X-Plex-Token": prefs.get("PlexOnlineToken"),
        "Accept": "application/json",
        "X-Plex-Client-Identifier": "nixflix-migration-check",
    }
    with urlopen(
        Request("http://127.0.0.1:32400/library/sections", headers=headers), timeout=30
    ) as response:
        report["plex_sections"] = json.load(response)["MediaContainer"]["size"]
    try:
        with urlopen(
            Request("https://plex.tv/api/v2/user", headers=headers), timeout=30
        ) as response:
            subscription = json.load(response).get("subscription", {})
        report["plex_pass"] = {
            k: subscription.get(k) for k in ("active", "status", "plan")
        }
    except Exception:
        report["plex_pass"] = "cloud verification unavailable"
    report["gpu_render_device"] = Path("/dev/dri/renderD128").exists()
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        with args.output.open("w") as file:
            os.chmod(args.output, 0o600)
            file.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
