#!/usr/bin/env python3
"""Resolve NNTP credentials through SecretSpec and publish a private generation."""

import importlib.util
import json
import os
from pathlib import Path
import sys

from nntp_credentials import KEYS, validate
from role import installed_role


def main():
    installed_role(production_only=True)
    os.umask(0o077)
    action = sys.argv[1]
    if action == "emit":
        values = {key: os.environ.get(key, "") for key in KEYS}
        validate(values)
        json.dump(values, sys.stdout)
        return
    if action != "install" or os.geteuid() != 0:
        raise ValueError("Installer requires root")
    spec = importlib.util.spec_from_file_location(
        "credential_installer", Path(__file__).with_name("provision-secrets.py")
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    installer.install(
        json.load(sys.stdin), Path("/var/lib/nixflix-nntp-secrets"),
        keys=KEYS, validator=validate,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit("NNTP provisioning failed; credential output suppressed.")
