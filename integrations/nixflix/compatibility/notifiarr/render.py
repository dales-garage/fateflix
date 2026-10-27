"""Resolve protected runtime inputs without putting secret values in Nix or logs."""

import configparser
import json
import os
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET


def resolve(value):
    if isinstance(value, list):
        return [resolve(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "_secret" not in value:
        return {key: resolve(item) for key, item in value.items()}
    path = Path(value["_secret"])
    fmt = value.get("format", "text")
    keys = value.get("key", [])
    if fmt == "xml":
        root = ET.parse(path).getroot()
        result = (
            root.get(keys[0][1:]) if keys[0].startswith("@") else root.findtext(keys[0])
        )
    elif fmt == "ini":
        data = configparser.ConfigParser(interpolation=None)
        data.read_string(path.read_text())
        result = data[keys[0]][keys[1]]
    else:
        result = path.read_text()
        if fmt == "json":
            result = json.loads(result)
        elif fmt == "yaml":
            import yaml

            result = yaml.safe_load(result)
        elif fmt != "text":
            raise ValueError("Unknown credential format")
        for key in keys:
            result = result[key]
    if not isinstance(result, str) or not result.strip():
        raise ValueError("Missing credential")
    result = result.strip()
    if any(char in result for char in "\r\n\x00"):
        raise ValueError("Credentials must be single-line values")
    return result


def main():
    import tomli_w

    os.umask(0o077)
    target = Path(sys.argv[2])
    content = tomli_w.dumps(resolve(json.loads(Path(sys.argv[1]).read_text())))
    owner = target.parent.stat()
    fd, name = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.chown(name, owner.st_uid, owner.st_gid)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(
            "Notifiarr configuration failed: check runtime credential files (values suppressed)."
        )
