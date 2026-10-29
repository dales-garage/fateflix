#!/usr/bin/env python3
"""Rewire copied integrations on nixflix; never submit searches.

Use the staging namespace before cutover, or the host namespace in production.
"""

import json
import argparse
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

INSTANCES = {
    "sonarr": (8990, "WEB-1080p (Alternative)"),
    "sonarr-4k": (8989, "WEB-2160p (Alternative)"),
    "radarr": (7879, "[SQP] SQP-1 (1080p)"),
    "radarr-4k": (7878, "[SQP] SQP-1 (2160p)"),
    "lidarr": (8686, None),
    "readarr": (8787, None),
    "whisparr": (6969, None),
}


def api(port, key, method, path, value=None, version="v3"):
    if port in (8686, 8787):
        version = "v1"
    req = Request(
        f"http://127.0.0.1:{port}/api/{version}/{path}",
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
        data=json.dumps(value).encode() if value is not None else None,
        method=method,
    )
    with urlopen(req, timeout=60) as response:
        body = response.read()
        return json.loads(body) if body else None


def secret(name):
    if name in ("readarr", "whisparr"):
        return ET.parse(Path("/var/lib", name, "config.xml")).findtext("ApiKey")
    return Path("/var/lib/nixflix-secrets/current", name).read_text().strip()


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    os.umask(0o077)
    prowlarr_key = secret("prowlarr")
    # Official retirement notice: https://nzb.su/ (same accounts and API keys).
    for indexer in api(9696, prowlarr_key, "GET", "indexer", version="v1"):
        changed = False
        for field in indexer.get("fields", []):
            if field["name"] != "baseUrl":
                continue
            url = urlsplit(str(field.get("value", "")))
            if url.hostname in ("nzb.su", "www.nzb.su", "api.nzb.su"):
                field["value"] = url._replace(
                    scheme="https", netloc="api.nzb.life"
                ).geturl()
                changed = True
        if changed:
            api(
                9696,
                prowlarr_key,
                "PUT",
                f"indexer/{indexer['id']}?forceSave=true",
                indexer,
                version="v1",
            )
    for app in api(9696, prowlarr_key, "GET", "applications", version="v1"):
        fields = {f["name"]: f for f in app["fields"]}
        port = urlsplit(fields["baseUrl"]["value"]).port
        if port not in (8990, 8989, 7879, 7878, 8686, 8787, 6969):
            continue
        fields["baseUrl"]["value"] = f"http://127.0.0.1:{port}"
        fields["prowlarrUrl"]["value"] = "http://127.0.0.1:9696"
        destination = next(
            name for name, values in INSTANCES.items() if values[0] == port
        )
        fields["apiKey"]["value"] = secret(destination)
        api(
            9696,
            prowlarr_key,
            "PUT",
            f"applications/{app['id']}?forceSave=true",
            app,
            version="v1",
        )
    for name, (port, _) in INSTANCES.items():
        key = secret(name)
        # Disabled/failing indexers are not always resynced by Prowlarr. Rewrite
        # their stored origin too, retaining provider paths, IDs and enable flags.
        for indexer in api(port, key, "GET", "indexer"):
            changed = False
            for field in indexer.get("fields", []):
                if field["name"] != "baseUrl":
                    continue
                url = urlsplit(str(field.get("value", "")))
                if url.hostname in ("prowlarr", "10.69.0.12") and url.port == 9696:
                    field["value"] = url._replace(netloc="127.0.0.1:9696").geturl()
                    changed = True
            if changed:
                api(
                    port, key, "PUT", f"indexer/{indexer['id']}?forceSave=true", indexer
                )
        # Preserve connection definitions, but do not revive retired webhook/bot
        # destinations while the user provisions Discord and Matrix.
        for notification in api(port, key, "GET", "notification"):
            changed = False
            for field in notification:
                if field.startswith("on") and notification[field] is True:
                    notification[field] = False
                    changed = True
            if changed:
                api(
                    port,
                    key,
                    "PUT",
                    f"notification/{notification['id']}?forceSave=true",
                    notification,
                )
        for item in api(port, key, "GET", "importlist"):
            changed = False
            for field in item.get("fields", []):
                value = field.get("value")
                if not isinstance(value, str) or not value.startswith(
                    ("http://", "https://")
                ):
                    continue
                url = urlsplit(value)
                if url.hostname in (
                    "10.69.0.12",
                    "sonarr",
                    "sonarr2",
                    "radarr",
                    "radarr2",
                    "prowlarr",
                    "overseerr",
                ):
                    if url.port in (
                        8990,
                        8989,
                        7879,
                        7878,
                        8686,
                        8787,
                        6969,
                        9696,
                        5055,
                    ):
                        field["value"] = url._replace(
                            netloc=f"127.0.0.1:{url.port}"
                        ).geturl()
                        changed = True
            if changed:
                api(port, key, "PUT", f"importlist/{item['id']}?forceSave=true", item)
        for client in api(port, key, "GET", "downloadclient"):
            if client["implementation"] != "Sabnzbd":
                continue
            fields = {f["name"]: f for f in client["fields"]}
            for field, value in {
                "host": "127.0.0.1",
                "port": 8080,
                "apiKey": secret("sabnzbd"),
            }.items():
                fields[field]["value"] = value
            for field in (
                "tvCategory",
                "movieCategory",
                "musicCategory",
                "bookCategory",
            ):
                if field in fields:
                    if name not in ("readarr", "whisparr"):
                        fields[field]["value"] = name
            api(
                port,
                key,
                "PUT",
                f"downloadclient/{client['id']}?forceSave=true",
                client,
            )
    # Stop the writer before editing copied Seerr settings, then atomically replace.
    subprocess.run(["systemctl", "stop", "seerr"], check=True)
    file = Path("/var/lib/seerr/settings.json")
    settings = json.loads(file.read_text())
    for app in ("sonarr", "radarr"):
        for destination in settings.get(app, []):
            name = app + ("-4k" if destination.get("is4k") else "")
            port, profile = INSTANCES[name]
            key = secret(name)
            matches = [
                p
                for p in api(port, key, "GET", "qualityprofile")
                if p["name"] == profile
            ]
            if len(matches) != 1:
                raise RuntimeError("Managed profile is missing")
            destination.update(
                hostname="127.0.0.1",
                port=port,
                apiKey=key,
                activeProfileId=matches[0]["id"],
                activeProfileName=profile,
            )
    pending = file.with_suffix(".pending")
    pending.write_text(json.dumps(settings, indent=2) + "\n")
    os.chown(pending, file.stat().st_uid, file.stat().st_gid)
    os.replace(pending, file)
    subprocess.run(["systemctl", "start", "seerr"], check=True)
    print("Configured Prowlarr, SABnzbd clients, and all four Seerr destinations.")


if __name__ == "__main__":
    main()
