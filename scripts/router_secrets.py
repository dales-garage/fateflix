"""Resolve the scoped DNS token through SecretSpec/pass without logging it."""

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
        "pass",
        "--",
        "sh",
        "-c",
        'printf %s "$' + name + '"',
    ]
    remote = 'set -eu\numask 077\nmanifest=$(mktemp --suffix=.toml)\ntrap \'rm -f "$manifest"\' EXIT\ncat > "$manifest"\n'
    remote += shlex.join(command).replace("MANIFEST_PATH", '"$manifest"')
    manifest = Path(__file__).resolve().parent.parent / "secretspec-router.toml"
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

    # Create once; never overwrite an existing password during provisioning.
    remote = """set -eu
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
