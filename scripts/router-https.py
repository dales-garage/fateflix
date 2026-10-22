#!/usr/bin/env python3
"""Manage router HTTPS: internal Caddy CA and selected public-domain routes.

Apply resolves the DNS token through SecretSpec/pass on nixflix and transmits it
over authenticated SSH. No token is accepted on the command line or printed.
"""

import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess
from router_secrets import dns_token, dashboard_password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["plan", "prepare", "apply", "ingress-plan", "ingress-apply"]
    )
    parser.add_argument("--router", default="root@10.42.0.1")
    parser.add_argument("--control-path")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    manifest = json.loads((root / "hosts/nixflix/local-services.json").read_text())
    script = (
        "router-ingress.php"
        if args.action.startswith("ingress-")
        else "router-https.php"
    )
    code = (root / "scripts" / script).read_text().removeprefix("<?php")
    command = [
        "/usr/local/bin/php",
        "-r",
        "eval(base64_decode('" + base64.b64encode(code.encode()).decode() + "'));",
    ]
    ssh = ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes"]
    if args.control_path:
        ssh += ["-o", "ControlPath=" + args.control_path]
    payload = {"action": args.action, "manifest": manifest}
    if args.action == "apply":
        payload["dns_token"] = dns_token()
        payload["web_password"] = dashboard_password()
    result = subprocess.run(
        ssh + [args.router, shlex.join(command)],
        input=json.dumps(payload),
        text=True,
        check=False,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
