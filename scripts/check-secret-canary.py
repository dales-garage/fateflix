#!/usr/bin/env python3
"""Build both hosts with runtime-only canaries; inspect configuration, derivations and logs.
Run on the NixFlix VM or CI. No production credential paths are read or written.
"""

import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "modules/_modules/secrets"
sys.path.insert(0, str(DIRECTORY))


def main():
    spec = importlib.util.spec_from_file_location(
        "installer", DIRECTORY / "provision-secrets.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    canary = secrets.token_hex(32)
    values = {name: canary for name in installer.KEYS}
    values["SMB_CREDENTIALS"] = "username=canary\npassword=" + canary + "\n"
    environment = os.environ | values
    with tempfile.TemporaryDirectory(prefix="fateflix-canary-") as directory:
        installer.install(values, Path(directory) / "credentials")
        targets = [
            f".#nixosConfigurations.nixflix-{role}.config.system.build.toplevel"
            for role in ["production", "staging"]
        ]
        build = subprocess.run(
            ["nix", "build", "--no-link", "--no-write-lock-file", "--json", *targets],
            cwd=ROOT,
            env=environment,
            capture_output=True,
        )
        if canary.encode() in build.stdout + build.stderr:
            raise ValueError("Canary appeared in build output")
        if build.returncode:
            raise ValueError(
                "Host build failed; run the ordinary build for diagnostics"
            )
        outputs = [entry["outputs"]["out"] for entry in json.loads(build.stdout)]
        derivations = subprocess.run(
            ["nix", "derivation", "show", "--recursive", *targets],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=True,
        )
        if canary.encode() in derivations.stdout + derivations.stderr:
            raise ValueError("Canary appeared in derivations")
        for output in outputs:
            # The built etc tree follows service/unit source links without traversing the entire package closure.
            for base, _, files in os.walk(Path(output) / "etc", followlinks=True):
                for name in files:
                    path = Path(base) / name
                    if path.is_file() and canary.encode() in path.read_bytes():
                        raise ValueError("Canary appeared in built configuration")
    print(
        "Both host closures built; runtime canary absent from configuration, derivations and build output."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError):
        sys.exit("Secret canary verification failed; credential output suppressed.")
