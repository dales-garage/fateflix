"""Resolve the scoped DNS token through SecretSpec/pass without logging it."""

import os
import re
import shlex
import subprocess
from pathlib import Path


def resolve(profile, name):
    command = [
        "secretspec",
        "--file",
        "MANIFEST_PATH",
        "run",
        "--profile",
        profile,
        "--provider",
        os.environ.get("SECRETSPEC_PROVIDER") or "pass",
        "--",
        "sh",
        "-c",
        'printf %s "$' + name + '"',
    ]
    remote = 'set -eu\ntest "$(cat /etc/nixflix/mode)" = production || exit 1\numask 077\nmanifest=$(mktemp --suffix=.toml)\ntrap \'rm -f "$manifest"\' EXIT\ncat > "$manifest"\n'
    remote += shlex.join(command).replace("MANIFEST_PATH", '"$manifest"')
    manifest = Path(__file__).resolve().parent / "secretspec-router.toml"
    result = subprocess.run(
        ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "marty@10.69.0.18", remote],
        input=manifest.read_text(),
        capture_output=True,
        text=True,
    )
    token = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[A-Za-z0-9_-]{20,}", token):
        raise RuntimeError(
            "Unable to resolve DNS token through SecretSpec/pass; no credential output displayed"
        )
    return token


def dns_token():
    return resolve("public_tls", "CLOUDFLARE_DNS_API_TOKEN")


def dashboard_password():
    import secrets

    if (os.environ.get("SECRETSPEC_PROVIDER") or "pass") != "pass":
        return resolve("router_web", "BASIC_AUTH_PASSWORD")

    # Create once; never overwrite an existing password during provisioning.
    remote = """set -eu
test "$(cat /etc/nixflix/mode)" = production || exit 1
if ! test -f "$HOME/.password-store/secretspec/nixflix/router_web/BASIC_AUTH_PASSWORD.gpg"; then
  pass insert -m secretspec/nixflix/router_web/BASIC_AUTH_PASSWORD >/dev/null
fi
"""
    result = subprocess.run(
        ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "marty@10.69.0.18", remote],
        input=secrets.token_urlsafe(32) + "\n",
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError("Unable to store public dashboard credential in pass")
    return resolve("router_web", "BASIC_AUTH_PASSWORD")
