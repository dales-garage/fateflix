#!/usr/bin/env python3
"""Resolve notification destinations through SecretSpec; atomically install as root."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

KEYS = {"DISCORD_APPRISE_URL": "discord", "MATRIX_APPRISE_URL": "matrixs"}


def configuration(values):
    if set(values) != set(KEYS):
        raise ValueError("Both notification destinations are required")
    urls = []
    for name, scheme in KEYS.items():
        value = values[name]
        if not isinstance(value, str) or any(c.isspace() or c == "\x00" for c in value):
            raise ValueError("Invalid notification destination")
        parsed = urlsplit(value)
        if parsed.scheme != scheme or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError("Invalid notification destination")
        urls.append({value: {"tag": ["media", "requests", "system"]}})
    return {"version": 1, "urls": urls}


def install(values, root):
    data = json.dumps(configuration(values)) + "\n"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.geteuid():
        raise ValueError("Unsafe credential directory")
    os.chmod(root, 0o700)
    target = root / "notifications.json"
    if target.is_file() and not target.is_symlink() and target.read_text() == data:
        os.chmod(target, 0o600)
        return
    fd, name = tempfile.mkstemp(prefix=".notifications-", dir=root)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, target)
        directory = os.open(root, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["emit", "install"])
    action = parser.parse_args().action
    os.umask(0o077)
    try:
        if action == "emit":
            values = {key: os.environ.get(key, "") for key in KEYS}
            configuration(values)
            json.dump(values, sys.stdout)
        else:
            if os.geteuid() != 0:
                raise ValueError("Installer requires root")
            install(json.load(sys.stdin), Path("/var/lib/nixflix-secrets"))
    except (ValueError, OSError, KeyError):
        sys.exit("Notification provisioning failed; no credential values were printed.")


if __name__ == "__main__":
    main()
