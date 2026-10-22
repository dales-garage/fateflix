#!/usr/bin/env python3
"""One-time importer on .18: JSON on stdin goes directly into pass."""

import json
import os
import subprocess
import sys

os.umask(0o077)
values = json.load(sys.stdin)
identity = "nixflix provisioning <nixflix@localhost>"
keys = (
    subprocess.check_output(
        ["gpg", "--batch", "--with-colons", "--list-secret-keys", identity],
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if subprocess.run(
        ["gpg", "--batch", "--list-secret-keys", identity],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    == 0
    else ""
)
if not keys:
    subprocess.run(
        [
            "gpg",
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            identity,
            "default",
            "default",
            "never",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    keys = subprocess.check_output(
        ["gpg", "--batch", "--with-colons", "--list-secret-keys", identity], text=True
    )
fingerprint = next(
    line.split(":")[9] for line in keys.splitlines() if line.startswith("fpr:")
)
subprocess.run(["pass", "init", fingerprint], check=True, stdout=subprocess.DEVNULL)
for key, value in values.items():
    if (
        not key.replace("_", "").isalnum()
        or not isinstance(value, str)
        or not value.strip()
    ):
        sys.exit("Invalid credential input")
    subprocess.run(
        [
            "pass",
            "insert",
            "--multiline",
            "--force",
            "secretspec/nixflix/default/" + key,
        ],
        input=value,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )
print("Imported credentials into pass; values were not logged.")
