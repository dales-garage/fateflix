#!/usr/bin/env python3
"""Resolve a Notifiarr key from SecretSpec, or install it from a private pipe."""

import os
from pathlib import Path
import re
import sys
import tempfile


def main():
    os.umask(0o077)
    action = sys.argv[1]
    value = (
        os.environ.get("NOTIFIARR_API_KEY", "")
        if action == "emit"
        else sys.stdin.read()
    ).strip()
    if not re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", value):
        raise ValueError("Invalid API key")
    if action == "emit":
        sys.stdout.write(value)
        return
    if action != "install" or os.geteuid() != 0:
        raise ValueError("Installer requires root")
    directory = Path("/var/lib/nixflix-secrets")
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / "notifiarr-api-key"
    if target.exists() and target.read_text() == value:
        return
    fd, name = tempfile.mkstemp(dir=directory, prefix=".notifiarr-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit("Notifiarr secret provisioning failed (values suppressed).")
