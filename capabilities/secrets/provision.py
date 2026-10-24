#!/usr/bin/env python3
"""Select the installed role before resolving any runtime credentials."""

import os
from pathlib import Path
import subprocess
import sys

from role import installed_role

OPERATIONS = {
    "provision": ("secretspec.toml", "default", "provision-secrets.py"),
    "provision-notifications": (
        "secretspec.toml",
        "notifications",
        "provision-notifications.py",
    ),
    "provision-notifiarr": (
        "secretspec-notifiarr.toml",
        "notifiarr",
        "provision-notifiarr.py",
    ),
}


def command(operation, role, provider, python=sys.executable):
    if role not in {"production", "staging"} or (
        role == "staging" and operation != "provision"
    ):
        raise ValueError("Credential operation is unavailable for this host role")
    manifest, profile, script = OPERATIONS[operation]
    if role == "staging":
        manifest = "secretspec-staging.toml"
    directory = Path(__file__).resolve().parent
    return [
        "secretspec",
        "--file",
        str(directory / manifest),
        "run",
        "--profile",
        profile,
        "--provider",
        provider,
        "--",
        python,
        str(directory / script),
        "emit",
    ]


def main():
    operation = sys.argv[1]
    role = installed_role(production_only=operation != "provision")
    cmd = command(operation, role, os.environ.get("SECRETSPEC_PROVIDER") or "pass")
    # Buffer only in memory. Provider output/errors never reach the terminal or journal.
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode:
        raise ValueError("Credential resolution failed")
    script = Path(__file__).resolve().parent / OPERATIONS[operation][2]
    result = subprocess.run(
        ["/run/wrappers/bin/sudo", "-n", sys.executable, str(script), "install"],
        input=result.stdout,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("Credential installation failed")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, IndexError):
        sys.exit("Secret provisioning failed; credential output suppressed.")
