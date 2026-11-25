#!/usr/bin/env python3
"""Apply quota guardrails and Prowlarr's direct SAB route without logging keys."""

import argparse
import copy
import json
from pathlib import Path
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET


def update_fields(record, desired):
    result = copy.deepcopy(record)
    fields = {field["name"]: field for field in result["fields"]}
    if not desired.keys() <= fields.keys():
        raise ValueError("Expected Prowlarr configuration fields are missing")
    for name, value in desired.items():
        fields[name]["value"] = value
    return result


def apply(policy, api, settings, sab_key):
    changed = []
    for record in api("indexer"):
        limit = policy["indexers"].get(record["name"])
        if limit is None:
            continue
        desired = {"baseSettings.queryLimit": limit["queries"],
            "baseSettings.grabLimit": limit["grabs"], "baseSettings.limitsUnit": 0}
        candidate = update_fields(record, desired)
        if candidate == record:
            continue
        provider_key = settings["Indexers"][record["id"]]["apiKey"]
        candidate = update_fields(candidate, {"apiKey": provider_key})
        api("indexer/" + str(record["id"]), "PUT", candidate)
        changed.append(record["name"])
    clients = [record for record in api("downloadclient")
        if record.get("enable") and record.get("implementation") == "Sabnzbd"
        and record["name"].lower() == "sabnzbd"]
    if len(clients) != 1:
        raise ValueError("Expected one enabled direct SAB download client")
    record = clients[0]
    candidate = update_fields(record, policy["sab_client"])
    repaired = candidate != record or settings["DownloadClients"][record["id"]].get("apiKey") != sab_key
    if repaired:
        candidate = update_fields(candidate, {"apiKey": sab_key})
        api("downloadclient/test", "POST", candidate)
        api("downloadclient/" + str(record["id"]), "PUT", candidate)
    return {"indexer_quotas_updated": changed, "sab_client_repaired": repaired}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--prowlarr-config", type=Path, default=Path("/var/lib/prowlarr/config.xml"))
    parser.add_argument("--prowlarr-database", type=Path, default=Path("/var/lib/prowlarr/prowlarr.db"))
    parser.add_argument("--sab-api-key-file", type=Path, default=Path("/var/lib/nixflix-secrets/current/sabnzbd"))
    args = parser.parse_args()
    key = ET.fromstring(args.prowlarr_config.read_bytes()).findtext("ApiKey")
    policy = json.loads(args.policy.read_text())
    connection = sqlite3.connect(args.prowlarr_database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        settings = {table: {row[0]: json.loads(row[1]) for row in connection.execute(
            "SELECT Id, Settings FROM " + table)} for table in ("Indexers", "DownloadClients")}
    finally:
        connection.close()
    def api(resource, method="GET", data=None):
        request = urllib.request.Request("http://127.0.0.1:9696/api/v1/" + resource,
            data=None if data is None else json.dumps(data).encode(),
            headers={"X-Api-Key": key, "Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
        return json.loads(raw) if raw else None
    result = apply(policy, api, settings, args.sab_api_key_file.read_text().strip())
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.exit("Usenet policy failed (" + type(error).__name__ + "); credential output suppressed.")
