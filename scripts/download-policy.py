#!/usr/bin/env python3
"""Disable disallowed protocols in restored Arr/Prowlarr state without deleting it."""

import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


def wait_for_api(call, deadline):
    """Probe readiness before modifying restored application records."""
    deadline = min(deadline, time.monotonic() + 90)
    while time.monotonic() < deadline:
        try:
            call("GET", "system/status")
            return
        except HTTPError as error:
            if error.code not in (408, 425, 429) and not 500 <= error.code < 600:
                raise
        except (ConnectionError, TimeoutError, URLError):
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(3, remaining))
    raise TimeoutError("Application readiness deadline exceeded")


def reconcile(call, *, prowlarr=False, torrents=False, usenet=True):
    """Only PUT changed records; enabling a protocol never enables a client."""
    denied = {
        name
        for name, allowed in [("torrent", torrents), ("usenet", usenet)]
        if not allowed
    }
    for resource in ["downloadclient", "indexer"]:
        for record in call("GET", resource):
            if str(record.get("protocol", "")).lower() not in denied:
                continue
            changed = False
            for field in (
                ["enable"]
                if resource == "downloadclient" or prowlarr
                else ["enableRss", "enableAutomaticSearch", "enableInteractiveSearch"]
            ):
                if record.get(field):
                    record[field] = False
                    changed = True
            if changed:
                call("PUT", f"{resource}/{record['id']}", record)
    # Arr validates that at least one protocol is enabled on a delay profile.
    # With neither allowed, disabling all clients/indexers already blocks grabs.
    if not prowlarr and (torrents or usenet):
        for profile in call("GET", "delayprofile"):
            previous = dict(profile)
            if not torrents:
                profile["enableTorrent"] = False
                profile["enableUsenet"] = True
                profile["preferredProtocol"] = "usenet"
            if not usenet:
                profile["enableUsenet"] = False
                profile["enableTorrent"] = True
                profile["preferredProtocol"] = "torrent"
            if previous != profile:
                call("PUT", f"delayprofile/{profile['id']}", profile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    failures = []
    deadline = time.monotonic() + 120
    for app in manifest["apps"]:
        name = app["name"]
        if Path(f"/var/lib/nixflix-gitops/holds/{name}").exists():
            continue
        if not Path(f"/var/lib/nixflix-migration/ready/{name}").exists():
            continue
        try:
            key = ET.parse(f"/var/lib/{name}/config.xml").findtext("ApiKey")
            if not key:
                raise ValueError("missing API key")

            def call(method, resource, payload=None):
                request = Request(
                    app["url"] + "/" + resource,
                    data=json.dumps(payload).encode() if payload is not None else None,
                    headers={"X-Api-Key": key, "Content-Type": "application/json"},
                    method=method,
                )
                with urlopen(request, timeout=10) as response:
                    return json.load(response)

            wait_for_api(call, deadline)
            reconcile(
                call,
                prowlarr=name == "prowlarr",
                torrents=manifest["torrents"],
                usenet=manifest["usenet"],
            )
        except Exception:
            # Avoid printing URLs, responses or exception text containing credentials.
            failures.append(name)
    if failures:
        raise SystemExit("Download policy failed for: " + ", ".join(failures))


if __name__ == "__main__":
    main()
