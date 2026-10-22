#!/usr/bin/env python3
"""Manage router Unbound records for the repository's Caddy service manifest.

Run from the workstation. Uses SSH authentication; no password or API secret is
stored. Plan validates without saving. Apply backs up router configuration first.
Remove deletes only this manifest's explicitly marked nixflix host overrides.
"""

import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply", "remove"])
    parser.add_argument("--router", default="root@10.42.0.1")
    parser.add_argument("--zone", choices=["internal", "public"], default="internal")
    parser.add_argument(
        "--control-path", help="Existing authenticated SSH multiplex socket"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    manifest = json.loads((root / "hosts/nixflix/local-services.json").read_text())
    manifest["address"] = manifest["routerAddress"]
    if args.zone == "public":
        manifest.update(domain="dalebox.pw")
        manifest["services"] = {
            manifest.get("publicNames", {}).get(name, name): manifest["services"][name]
            for name in manifest["publicServices"]
        }
    code = (root / "scripts/router-dns.php").read_text().removeprefix("<?php")
    # PHP code is encoded to pass intact through either csh or a POSIX login shell.
    command = [
        "/usr/local/bin/php",
        "-r",
        "eval(base64_decode('" + base64.b64encode(code.encode()).decode() + "'));",
    ]
    ssh = ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes"]
    if args.control_path:
        ssh += ["-o", "ControlPath=" + args.control_path]
    subprocess.run(
        ssh + [args.router, shlex.join(command)],
        input=json.dumps({"action": args.action, "manifest": manifest}),
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
