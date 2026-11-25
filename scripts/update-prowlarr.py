#!/usr/bin/env python3
"""Refresh the official stable fallback, verifying every asset before writing."""

import base64
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = "https://api.github.com/repos/Prowlarr/Prowlarr/releases/latest"


def fetch(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "fateflix-updater"}),
        timeout=120,
    )


def main():
    with fetch(URL) as response:
        release = json.load(response)
    if release["draft"] or release["prerelease"]:
        raise ValueError("Expected a stable release")
    version = release["tag_name"].removeprefix("v")
    if len(version.split(".")) != 4 or not all(p.isdigit() for p in version.split(".")):
        raise ValueError("Unexpected release version")
    sources = {}
    for system, arch in [("x86_64-linux", "x64"), ("aarch64-linux", "arm64")]:
        name = f"Prowlarr.master.{version}.linux-core-{arch}.tar.gz"
        asset = next(a for a in release["assets"] if a["name"] == name)
        url = asset["browser_download_url"]
        if not url.startswith(
            "https://github.com/Prowlarr/Prowlarr/releases/download/"
        ):
            raise ValueError("Unexpected asset origin")
        digest = hashlib.sha256()
        with fetch(url) as response:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
        if asset.get("digest") != "sha256:" + digest.hexdigest():
            raise ValueError(f"Missing or mismatched official digest: {name}")
        sources[system] = {
            "url": url,
            "hash": "sha256-" + base64.b64encode(digest.digest()).decode(),
        }
        print(f"Verified {name}")
    output = ROOT / "pkgs/prowlarr-upstream/sources.json"
    content = json.dumps({"version": version, "sources": sources}, indent=2) + "\n"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(content)
    temporary.replace(output)
    print(f"Updated {output.relative_to(ROOT)} to {version}")


if __name__ == "__main__":
    main()
