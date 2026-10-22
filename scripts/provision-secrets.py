#!/usr/bin/env python3
"""Resolve with SecretSpec as marty, pipe JSON into the root installer.
No values are logged, put in argv, or embedded in Nix expressions.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import fcntl

KEYS = {
    "SMB_CREDENTIALS": "smb",
    "SONARR_API_KEY": "sonarr",
    "SONARR_4K_API_KEY": "sonarr-4k",
    "RADARR_API_KEY": "radarr",
    "RADARR_4K_API_KEY": "radarr-4k",
    "LIDARR_API_KEY": "lidarr",
    "PROWLARR_API_KEY": "prowlarr",
    "SABNZBD_API_KEY": "sabnzbd",
}


def validate(values):
    if set(values) != set(KEYS) or any(
        not isinstance(v, str) or not v.strip() or "\x00" in v for v in values.values()
    ):
        raise ValueError("Missing or invalid required credentials")
    lines = dict(
        line.split("=", 1)
        for line in values["SMB_CREDENTIALS"].splitlines()
        if "=" in line
    )
    if not lines.get("username") or not lines.get("password"):
        raise ValueError("SMB credentials require username and password")
    for key, value in values.items():
        if key != "SMB_CREDENTIALS" and (
            "\n" in value.strip() or "\r" in value.strip()
        ):
            raise ValueError("API credentials must be single-line values")


def install(values, root):
    validate(values)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.geteuid():
        raise ValueError("Credential directory has unsafe ownership")
    os.chmod(root, 0o700)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = root / "current"
        if current.is_symlink() and all(
            (current / name).read_text() == values[key] for key, name in KEYS.items()
        ):
            return
        generation = Path(tempfile.mkdtemp(prefix="generation-", dir=root))
        try:
            for key, name in KEYS.items():
                path = generation / name
                with path.open("x") as f:
                    os.chmod(path, 0o600)
                    f.write(values[key])
                    f.flush()
                    os.fsync(f.fileno())
            link = root / ".next"
            link.unlink(missing_ok=True)
            link.symlink_to(generation.name)
            os.replace(link, current)
            fd = os.open(root, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except BaseException:
            if not current.is_symlink() or current.resolve() != generation:
                shutil.rmtree(generation)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["emit", "install"])
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "emit":
            values = {key: os.environ.get(key, "") for key in KEYS}
            validate(values)
            json.dump(values, sys.stdout)
        else:
            if os.geteuid() != 0:
                raise ValueError("Installer must run as root")
            install(json.load(sys.stdin), Path("/var/lib/nixflix-secrets"))
    except (ValueError, OSError, KeyError):
        sys.exit("Secret provisioning failed; no credential values were printed.")


if __name__ == "__main__":
    main()
