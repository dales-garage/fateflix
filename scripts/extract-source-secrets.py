#!/usr/bin/env python3
"""Run as root on .12; pipe stdout directly to import-pass.py on .18."""

import json
from pathlib import Path
import re
import shlex
import sys
import xml.etree.ElementTree as ET

result = {}
for name, target in [
    ("sonarr2", "SONARR_API_KEY"),
    ("sonarr", "SONARR_4K_API_KEY"),
    ("radarr2", "RADARR_API_KEY"),
    ("radarr", "RADARR_4K_API_KEY"),
    ("lidarr", "LIDARR_API_KEY"),
    ("prowlarr", "PROWLARR_API_KEY"),
]:
    result[target] = ET.parse("/docker/" + name + "-config/config.xml").findtext(
        "ApiKey"
    )
sab = Path("/docker/sabnzbd-config/sabnzbd.ini").read_text()
result["SABNZBD_API_KEY"] = re.search(r"^api_key\s*=\s*(\S+)", sab, re.M).group(1)
for line in Path("/etc/fstab").read_text().splitlines():
    fields = shlex.split(line, comments=True)
    if len(fields) < 4 or fields[0] != "//10.69.0.10/data":
        continue
    options = dict(part.split("=", 1) for part in fields[3].split(",") if "=" in part)
    if "credentials" in options:
        result["SMB_CREDENTIALS"] = Path(options["credentials"]).read_text()
    else:
        creds = {
            "username": options.get("username", options.get("user")),
            "password": options.get("password", options.get("pass")),
        }
        if options.get("domain"):
            creds["domain"] = options["domain"]
        if not all(creds.values()):
            sys.exit("Missing NAS credential fields")
        result["SMB_CREDENTIALS"] = "".join(
            k + "=" + v + "\n" for k, v in creds.items()
        )
if "SMB_CREDENTIALS" not in result:
    sys.exit("NAS entry was not found")
json.dump(result, sys.stdout)
