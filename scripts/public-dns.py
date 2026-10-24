#!/usr/bin/env python3
"""Publish only approved public media names to the router's WAN IPv4 address."""

import argparse
import datetime
import ipaddress
import json
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen
from router_secrets import dns_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply"])
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    if not ipaddress.IPv4Address(args.address).is_global:
        parser.error("a global WAN IPv4 address is required")
    manifest = json.loads(
        (
            Path(__file__).resolve().parent.parent / "hosts/nixflix/local-services.json"
        ).read_text()
    )
    token = dns_token()

    def api(path, method="GET", body=None):
        request = Request(
            "https://api.cloudflare.com/client/v4/" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
        if not data.get("success"):
            raise RuntimeError("Cloudflare DNS operation failed")
        return data

    zones = api("zones?name=dalebox.pw")["result"]
    if len(zones) != 1:
        raise RuntimeError("Expected exactly one dalebox.pw zone")
    base = "zones/" + zones[0]["id"] + "/dns_records"
    data = api(base + "?per_page=100")
    if data.get("result_info", {}).get("total_pages", 1) > 1:
        raise RuntimeError("DNS zone requires pagination; review before modifying")
    records = data["result"]
    forbidden = {"stash.dalebox.pw", "whisparr.dalebox.pw", "*.dalebox.pw"}
    if any(
        r["name"] in forbidden and r["type"] in ("A", "AAAA", "CNAME") for r in records
    ):
        raise RuntimeError(
            "Forbidden public service or wildcard DNS record exists; review required"
        )
    changes = []
    for service in manifest["publicServices"]:
        name = manifest.get("publicNames", {}).get(service, service) + ".dalebox.pw"
        existing = [
            r
            for r in records
            if r["name"] == name and r["type"] in ("A", "AAAA", "CNAME")
        ]
        if len(existing) > 1 or (existing and existing[0]["type"] == "AAAA"):
            raise RuntimeError("Unexpected multiple-address or IPv6 record: " + name)
        old = existing[0] if existing else None
        wanted = {
            "type": "A",
            "name": name,
            "content": args.address,
            "ttl": 120,
            "proxied": False,
        }
        if old is None or any(old.get(k) != v for k, v in wanted.items()):
            changes.append((old, wanted))
    backup = None
    if args.action == "apply" and changes:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = "/var/lib/nixflix-migration/public-dns-" + stamp + ".json"
        command = "sudo -n sh -c 'umask 077; cat > " + backup + "'"
        subprocess.run(
            [
                "ssh",
                "-F",
                "/dev/null",
                "-o",
                "BatchMode=yes",
                "marty@10.69.0.18",
                command,
            ],
            input=json.dumps({"zone": zones[0]["id"], "changes": changes}, indent=2),
            text=True,
            check=True,
        )
        for old, wanted in changes:
            api(
                base + ("/" + old["id"] if old else ""),
                "PUT" if old else "POST",
                wanted,
            )
    print(
        json.dumps(
            {
                "action": args.action,
                "names": [wanted["name"] for _, wanted in changes],
                "address": args.address,
                "backup": backup,
                "forbidden_names_absent": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
