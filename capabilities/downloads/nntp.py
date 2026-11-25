#!/usr/bin/env python3
"""Apply public NNTP server policy using private systemd credentials."""

import argparse
import copy
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


def configure(config, credentials, policy):
    required = set(policy["credentials"])
    if set(credentials) != required or any(
        not isinstance(value, str) or not value or len(value) > 4096
        or any(c in value for c in ("\x00", "\n", "\r"))
        for value in credentials.values()
    ):
        raise ValueError("Missing or invalid NNTP credentials")
    result = copy.deepcopy(config)
    servers = result.setdefault("servers", {})
    for old, new in policy.get("rename", {}).items():
        if old in servers and new not in servers:
            if hasattr(servers, "rename"):
                servers.rename(old, new)
            else:
                servers[new] = servers.pop(old)
        elif old in servers:
            servers[old]["enable"] = "0"
    for server in policy["servers"]:
        section = servers.setdefault(server["name"], {})
        for key in ("host", "port", "connections", "ssl", "ssl_verify", "enable"):
            section[key] = str(server[key])
        section["username"] = credentials[server["username_key"]]
        section["password"] = credentials[server["password_key"]]
    for alias, canonical in policy.get("disabled_aliases", {}).items():
        if alias in servers:
            servers[alias]["username"] = servers[canonical]["username"]
            servers[alias]["password"] = servers[canonical]["password"]
            servers[alias]["enable"] = "0"
    for section in servers.values():
        if "retention" in policy:
            section["retention"] = str(policy["retention"])
    misc = result.setdefault("misc", {})
    for key, value in policy.get("misc", {}).items():
        misc[key] = str(value)
    categories = result.setdefault("categories", {})
    for name, category in policy.get("categories", {}).items():
        categories[name] = {key: str(value) for key, value in category.items()}
    return result


def apply(path, credentials, policy):
    from configobj import ConfigObj

    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Unsafe SAB configuration path")
    original = path.read_bytes()
    config = ConfigObj(original.decode().splitlines(), encoding="utf-8")
    updated = configure(config, credentials, policy)
    output = io.BytesIO()
    updated.write(output)
    data = output.getvalue()
    if data == original:
        return
    fd, temporary = tempfile.mkstemp(prefix=".nntp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--credential-directory", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    values = {key: (args.credential_directory / key).read_text() for key in policy["credentials"]}
    apply(args.config, values, policy)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit("NNTP configuration failed; credential output suppressed.")
