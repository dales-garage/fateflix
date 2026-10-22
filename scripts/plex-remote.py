#!/usr/bin/env python3
"""Configure Plex remote access on nixflix without exposing its account token."""

import argparse
import json
import os
import socket
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "apply"])
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname() != "nixflix":
        parser.error("run as root on nixflix")
    prefs = ET.parse("/var/lib/plex/Plex Media Server/Preferences.xml").getroot()
    headers = {"X-Plex-Token": prefs.get("PlexOnlineToken")}

    def request(path, method="GET"):
        with urlopen(
            Request("http://127.0.0.1:32400" + path, headers=headers, method=method),
            timeout=30,
        ) as response:
            return response.read()

    if args.action == "apply":
        settings = {
            "ManualPortMappingMode": "1",
            "ManualPortMappingPort": "32400",
            "PublishServerOnPlexOnlineKey": "1",
            "customConnections": "https://plex.dalebox.pw:443",
        }
        request("/:/prefs?" + urlencode(settings), "PUT")
    state = ET.fromstring(request("/myplex/account"))
    print(
        json.dumps(
            {
                key: state.get(key)
                for key in (
                    "mappingState",
                    "mappingError",
                    "signInState",
                    "publicAddress",
                    "publicPort",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
