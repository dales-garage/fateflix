#!/usr/bin/env python3
"""Refresh the stable Whisparr v2 release and verify its official binary asset."""

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import tarfile
import tempfile
from urllib.request import Request, urlopen

VERSION = r"2\.\d+\.\d+-release\.\d+"


def version_key(value):
    if not re.fullmatch(VERSION, value):
        raise ValueError("Expected a stable Whisparr v2 release")
    return tuple(map(int, re.findall(r"\d+", value)))


def fetch(url):
    with urlopen(
        Request(url, headers={"User-Agent": "nixflix-package-updater"}), timeout=60
    ) as response:
        return response.read()


def release_hash(data, digest=None):
    value = hashlib.sha256(data).digest()
    if digest and digest != "sha256:" + value.hex():
        raise ValueError("Release asset digest mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        binary = archive.extractfile("Whisparr/Whisparr").read(20)
        if (
            binary[:6] != b"\x7fELF\x02\x01"
            or struct.unpack_from("<H", binary, 18)[0] != 62
        ):
            raise ValueError("Expected the Linux x64 executable")
        config = json.load(archive.extractfile("Whisparr/Whisparr.runtimeconfig.json"))
        if not config.get("runtimeOptions", {}).get("tfm", "").startswith("net"):
            raise ValueError("Expected the .NET application runtime configuration")
        if archive.getmember("Whisparr/Whisparr.dll").size == 0:
            raise ValueError("Application assembly is empty")
    return "sha256-" + base64.b64encode(value).decode()


def updated_source(source, release, downloader=fetch):
    version = release["tag_name"].removeprefix("v")
    current = re.search(r'version = "([^"]+)";', source)[1]
    if release["prerelease"] or release["draft"]:
        raise ValueError("Expected a published stable release")
    if version_key(version) < version_key(current):
        raise ValueError("Refusing to downgrade")
    if version == current:
        return source
    name = f"Whisparr.{version}.linux-x64.tar.gz"
    asset = next(a for a in release["assets"] if a["name"] == name)
    url = f"https://github.com/Whisparr/Whisparr/releases/download/v{version}/{name}"
    value = release_hash(downloader(url), asset.get("digest"))
    result, count = re.subn(r'(hash = ")[^"]+', lambda m: m[1] + value, source)
    if count != 1:
        raise ValueError("Expected exactly one source hash")
    return result.replace(f'version = "{current}";', f'version = "{version}";')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?")
    args = parser.parse_args()
    if args.version:
        version_key(args.version)
    release = json.loads(
        fetch(
            "https://api.github.com/repos/Whisparr/Whisparr/releases/"
            + ("tags/v" + args.version if args.version else "latest")
        )
    )
    if args.version and release["tag_name"] != "v" + args.version:
        raise ValueError("Release did not match requested version")
    path = Path(__file__).with_name("default.nix")
    before = path.read_text()
    after = updated_source(before, release, fetch)
    if after == before:
        print("Whisparr is already current.")
        return
    fd, name = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), path.stat().st_mode & 0o777)
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    print("Updated Whisparr to " + release["tag_name"])


if __name__ == "__main__":
    main()
