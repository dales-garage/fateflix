#!/usr/bin/env python3
"""Update both official Linux binaries and their fixed-output hashes atomically."""

import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
from urllib.request import Request, urlopen


def fetch(url):
    with urlopen(
        Request(url, headers={"User-Agent": "nixflix-package-updater"}), timeout=60
    ) as response:
        return response.read()


def release_hash(data, machine, digest=None):
    actual = hashlib.sha256(data).hexdigest()
    if digest and digest != "sha256:" + actual:
        raise ValueError("Release asset digest mismatch")
    binary = gzip.decompress(data)
    if (
        binary[:6] != b"\x7fELF\x02\x01"
        or struct.unpack_from("<H", binary, 18)[0] != machine
    ):
        raise ValueError("Unexpected executable format or architecture")
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode()


def main():
    path = Path(__file__).with_name("default.nix")
    source = path.read_text()
    release = json.loads(
        fetch("https://api.github.com/repos/Notifiarr/notifiarr/releases/latest")
    )
    version = release["tag_name"].removeprefix("v")
    if (
        not re.fullmatch(r"\d+\.\d+\.\d+", version)
        or release["prerelease"]
        or release["draft"]
    ):
        raise ValueError("Expected a stable release")
    current = re.search(r'version = "([^"]+)";', source).group(1)
    if current == version:
        print("Notifiarr is already current.")
        return
    if tuple(map(int, version.split("."))) < tuple(map(int, current.split("."))):
        raise ValueError("Refusing to downgrade")
    for arch, machine in [("amd64", 62), ("arm64", 183)]:
        name = f"notifiarr.{arch}.linux.gz"
        asset = next(a for a in release["assets"] if a["name"] == name)
        url = f"https://github.com/Notifiarr/notifiarr/releases/download/v{version}/{name}"
        value = release_hash(fetch(url), machine, asset.get("digest"))
        source, count = re.subn(
            r'(arch = "' + arch + r'";\s*hash = ")[^"]+', lambda m: m[1] + value, source
        )
        if count != 1:
            raise ValueError("Package architecture block not found")
    source = source.replace(f'version = "{current}";', f'version = "{version}";')
    path.write_text(source)


if __name__ == "__main__":
    main()
