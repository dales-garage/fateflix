#!/usr/bin/env python3
"""Copy inactive staged Podman state to native service directories on nixflix.

The original staged state remains available for rollback. New native readiness
markers are written only after the complete copy has the service user's ownership.
"""

import argparse
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess

NAMES = ["bazarr", "bazarr-4k", "tautulli", "audiobookshelf", "readarr", "whisparr"]


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    if os.geteuid() != 0 or socket.gethostname() != "nixflix":
        raise RuntimeError("Run as root on nixflix")
    os.umask(0o077)
    root = Path("/var/lib/nixflix-containers")
    ready = Path("/var/lib/nixflix-migration/ready")
    for name in NAMES:
        for unit in (name, "podman-" + name):
            if (
                subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode
                == 0
            ):
                raise RuntimeError("Stop " + unit + " before copying")
        target = Path("/var/lib") / name
        if (ready / name).exists():
            print(name + ": already prepared")
            continue
        if target.exists() and any(target.iterdir()):
            raise RuntimeError(
                str(target) + " is nonempty; preserve and inspect before retrying"
            )
        if name == "audiobookshelf":
            shutil.copytree(root / name, target / "config", symlinks=True)
            shutil.copytree(
                root / (name + "-metadata"), target / "metadata", symlinks=True
            )
        else:
            shutil.copytree(root / name, target, symlinks=True, dirs_exist_ok=True)
        owner = pwd.getpwnam(name)
        for directory, dirs, files in os.walk(target):
            os.chown(directory, owner.pw_uid, owner.pw_gid)
            os.chmod(directory, 0o700)
            for entry in files:
                file = Path(directory) / entry
                if not file.is_symlink():
                    os.chown(file, owner.pw_uid, owner.pw_gid)
                    os.chmod(file, 0o700 if file.stat().st_mode & 0o111 else 0o600)
        (ready / name).write_text("Native copy from " + str(root / name) + "\n")
        print(name + ": copied to native state; original retained")


if __name__ == "__main__":
    main()
