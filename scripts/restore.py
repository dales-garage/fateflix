#!/usr/bin/env python3
"""Restore one protected snapshot into an inactive target service's local state."""

import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess

NATIVE = {
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
    "whisparr",
    "readarr",
    "tautulli",
    "audiobookshelf",
}
CONTAINERS = {
    "mylar3",
    "notifiarr",
    "audiobookshelf-metadata",
    "stash",
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("service", choices=sorted(NATIVE | CONTAINERS))
    a = p.parse_args()
    if os.geteuid() != 0:
        p.error("run on .18 as root")
    manifest = json.loads((a.snapshot / "snapshot.json").read_text())
    if not manifest.get("completed") or a.service not in manifest["services"]:
        p.error("snapshot is incomplete")
    name = a.service
    if name == "audiobookshelf-metadata":
        p.error(
            "restore audiobookshelf; its metadata is now restored together with its native config"
        )
    unit = name if name in NATIVE else "podman-" + name
    if subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0:
        p.error("stop the target service before restoring")
    target = (
        Path("/var/lib") / name
        if name in NATIVE
        else Path("/var/lib/nixflix-containers") / name
    )
    marker = Path("/var/lib/nixflix-migration/ready") / unit
    if marker.exists():
        p.error(
            "already restored; preserve current state before an explicit replacement"
        )
    if target.exists() and any(target.iterdir()):
        p.error("target is nonempty; preserve it before restoring")
    os.umask(0o077)
    if name == "audiobookshelf":
        shutil.copytree(a.snapshot / name, target / "config", dirs_exist_ok=True)
        shutil.copytree(
            a.snapshot / "audiobookshelf-metadata",
            target / "metadata",
            dirs_exist_ok=True,
        )
    else:
        shutil.copytree(a.snapshot / name, target, dirs_exist_ok=True)
    if name in ("bazarr", "bazarr-4k"):
        import yaml

        file = target / "config/config.yaml"
        settings = yaml.safe_load(file.read_text())
        fourk = name.endswith("-4k")
        settings["general"]["port"] = 6777 if fourk else 6767
        settings["sonarr"].update(ip="127.0.0.1", port=8989 if fourk else 8990)
        settings["radarr"].update(ip="127.0.0.1", port=7878 if fourk else 7879)
        file.write_text(yaml.safe_dump(settings, sort_keys=False))
    if name == "sabnzbd":
        from configobj import ConfigObj

        file = target / "sabnzbd.ini"
        settings = ConfigObj(str(file))

        def rewrite(section):
            for key, value in section.items():
                if isinstance(value, dict):
                    rewrite(value)
                elif isinstance(value, str) and (
                    value == "/config" or value.startswith("/config/")
                ):
                    section[key] = str(target) + value[7:]

        rewrite(settings)
        settings["misc"]["host"] = "127.0.0.1"
        settings["misc"]["port"] = "8080"
        settings.write()
    if name == "seerr":
        file = target / "settings.json"
        settings = json.loads(file.read_text())
        if settings.get("plex"):
            settings["plex"]["ip"] = "127.0.0.1"
            settings["plex"]["port"] = 32400
        for app, hd, uhd in [("sonarr", 8990, 8989), ("radarr", 7879, 7878)]:
            for instance in settings.get(app, []):
                instance["hostname"] = "127.0.0.1"
                instance["port"] = uhd if instance.get("is4k") else hd
        file.write_text(json.dumps(settings, indent=2) + "\n")
    if name == "tautulli":
        from configobj import ConfigObj

        file = target / "config.ini"
        settings = ConfigObj(str(file))
        settings["PMS"]["pms_ip"] = "127.0.0.1"
        settings["PMS"]["pms_port"] = "32400"
        settings.write()
    owner = pwd.getpwnam(name if name in NATIVE else "media-container")
    for directory, dirs, files in os.walk(target):
        os.chown(directory, owner.pw_uid, owner.pw_gid)
        os.chmod(directory, 0o700)
        for file in files:
            path = Path(directory) / file
            if not path.is_symlink():
                os.chown(path, owner.pw_uid, owner.pw_gid)
                os.chmod(path, 0o700 if path.stat().st_mode & 0o111 else 0o600)
    # Service prestarts may need to recreate these omitted cache directories.
    if name == "stash":
        for part in ("cache", "generated", "metadata", "config"):
            (target / part).mkdir(exist_ok=True)
    marker.parent.mkdir(mode=0o700, exist_ok=True)
    marker.write_text(str(a.snapshot) + "\n")
    print("Restored " + name + "; service remains stopped")


if __name__ == "__main__":
    main()
