#!/usr/bin/env python3
"""Reconcile notification connections, preserving unrelated providers and backups."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

from render import resolve


def request(url, key, method="GET", data=None, form=False):
    headers = {"X-Api-Key": key, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
        data = (
            urllib.parse.urlencode(data, doseq=True) if form else json.dumps(data)
        ).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None


def backup(name, value):
    path = Path("/var/lib/notifiarr-connections") / (name + ".before.json")
    if not path.exists():
        with path.open("x") as stream:
            json.dump(value, stream)


def notification(schema, existing, key):
    matches = [item for item in existing if item["implementation"] == "Notifiarr"]
    if len(matches) > 1:
        raise ValueError("Multiple existing Notifiarr connections need reconciliation")
    current = matches[0] if matches else None
    result = copy.deepcopy(
        current
        or next(item for item in schema if item["implementation"] == "Notifiarr")
    )
    result["name"] = current["name"] if current else "Notifiarr"
    for field in result["fields"]:
        if field["name"].lower() == "apikey":
            field["value"] = key
    for name, supported in list(result.items()):
        if name.startswith("supportsOn") and supported:
            trigger = name.removeprefix("supports")
            result[trigger[0].lower() + trigger[1:]] = True
    return current, result


def connect_arr(app, key):
    url = app["url"] + "/api/" + app["apiVersion"] + "/notification"
    existing = request(url, app["api_key"])
    schema = request(url + "/schema", app["api_key"])
    current, desired = notification(schema, existing, key)
    # Most Arr APIs mask saved keys. Remember only the digest of a successful
    # application, so reboots do not retrigger provider validation unnecessarily.
    marker = Path("/var/lib/notifiarr-connections") / (app["name"] + ".key.sha256")
    digest = hashlib.sha256(key.encode()).hexdigest()
    comparison = copy.deepcopy(current)
    if current and marker.exists() and marker.read_text() == digest:
        for field in comparison["fields"]:
            value = field.get("value")
            if (
                field["name"].lower() == "apikey"
                and isinstance(value, str)
                and value
                and set(value) == {"*"}
            ):
                field["value"] = key
    if comparison == desired:
        return
    backup(app["name"], existing)
    suffix = "/" + str(current["id"]) if current else ""
    request(url + suffix, app["api_key"], "PUT" if current else "POST", desired)
    marker.write_text(digest)


def seerr_payload():
    payload = {
        name: "{{" + name + "}}"
        for name in ("notification_type", "event", "subject", "message", "image")
    }
    payload["{{media}}"] = {
        "media_type": "{{media_type}}",
        "imdbId": "{{media_imdbid}}",
        "tmdbId": "{{media_tmdbid}}",
        "tvdbId": "{{media_tvdbid}}",
        "status": "{{media_status}}",
        "status4k": "{{media_status4k}}",
    }
    for kind, fields in {
        "request": [
            "request_id",
            "requestedBy_email",
            "requestedBy_username",
            "requestedBy_avatar",
            "requestedBy_settings_discordIds",
        ],
        "issue": [
            "issue_id",
            "issue_type",
            "issue_status",
            "reportedBy_email",
            "reportedBy_username",
            "reportedBy_avatar",
            "reportedBy_settings_discordIds",
        ],
        "comment": [
            "comment_message",
            "commentedBy_email",
            "commentedBy_username",
            "commentedBy_avatar",
            "commentedBy_settings_discordIds",
        ],
    }.items():
        payload["{{" + kind + "}}"] = {field: "{{" + field + "}}" for field in fields}
    payload["{{extra}}"] = []
    # The HTTP API accepts JSON text and performs its own base64 encoding on disk.
    return json.dumps(payload)


def connect_seerr(app, key):
    url = app["url"] + "/api/v1/settings/notifications/webhook"
    current = request(url, app["api_key"])
    old_url = current.get("options", {}).get("webhookUrl", "")
    if current.get("enabled") and not old_url.startswith("https://notifiarr.com/"):
        raise ValueError("Seerr already has an enabled unrelated webhook")
    desired = copy.deepcopy(current)
    desired.update(enabled=True, types=4094)
    desired.setdefault("options", {}).update(
        webhookUrl="https://notifiarr.com/api/v1/notification/seerr/" + key,
        jsonPayload=seerr_payload(),
        customHeaders=[],
        supportVariables=False,
    )
    desired["options"].pop("authHeader", None)
    # Seerr versions return either parsed JSON or JSON text from this endpoint.
    comparison = copy.deepcopy(current)
    old_payload = comparison["options"].get("jsonPayload")
    if isinstance(old_payload, str):
        old_payload = json.loads(old_payload)
    comparison["options"]["jsonPayload"] = old_payload
    expected = copy.deepcopy(desired)
    expected["options"]["jsonPayload"] = json.loads(desired["options"]["jsonPayload"])
    if comparison == expected:
        return
    backup("seerr", current)
    request(url, app["api_key"], "POST", desired)


def connect_bazarr(app, key):
    url = app["url"] + "/api/system/settings"
    settings = request(url, app["api_key"])
    providers = settings["notifications"]["providers"]
    current = next(item for item in providers if item["name"] == "JSON")
    desired = {
        "name": "JSON",
        "enabled": True,
        "url": "jsons://notifiarr.com/api/v1/notification/bazarr/"
        + key
        + "?:instance="
        + urllib.parse.quote(app["name"]),
    }
    if current == desired:
        return
    if current["enabled"] and not current["url"].startswith("jsons://notifiarr.com/"):
        raise ValueError("Bazarr already has an enabled unrelated JSON provider")
    backup(app["name"], providers)
    request(
        url,
        app["api_key"],
        "POST",
        {"notifications-providers": json.dumps(desired)},
        form=True,
    )


def connect_plex(app, webhook):
    # Plex account webhooks apply to owned servers; preserve every existing URL.
    url = "https://plex.tv/api/v2/user/webhooks"
    headers = {
        "X-Plex-Token": app["token"],
        "Accept": "application/json",
        "X-Plex-Client-Identifier": "nixflix-notifiarr",
        "X-Plex-Product": "Nixflix",
    }
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=30
    ) as response:
        current = json.load(response)
    urls = [item["url"] for item in current]
    desired = webhook + "?token=" + urllib.parse.quote(app["token"])
    if desired in urls:
        return
    backup("plex-webhooks", current)
    urls.append(desired)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    data = urllib.parse.urlencode({"urls[]": urls}, doseq=True).encode()
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers, method="POST"),
        timeout=30,
    ):
        pass


def main():
    os.umask(0o077)
    cfg = resolve(json.loads(Path(sys.argv[1]).read_text()))
    jobs = [
        (app["name"], lambda app=app: connect_arr(app, cfg["apiKey"]))
        for app in cfg["arr"]
    ]
    jobs += [("seerr", lambda: connect_seerr(cfg["seerr"], cfg["apiKey"]))]
    jobs += [
        (app["name"], lambda app=app: connect_bazarr(app, cfg["apiKey"]))
        for app in cfg["bazarr"]
    ]
    jobs += [("plex-webhooks", lambda: connect_plex(cfg["plex"], cfg["plexWebhook"]))]
    failed = []
    for name, job in jobs:
        for attempt in range(3):
            try:
                job()
                print(name + ": configured", flush=True)
                break
            except (ConnectionError, TimeoutError, urllib.error.URLError):
                if attempt == 2:
                    failed.append(name)
                else:
                    time.sleep(3)
            except Exception:
                failed.append(name)
                break
    if failed:
        sys.exit(
            "Notifiarr connections failed (details suppressed to protect credentials): "
            + ", ".join(failed)
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(
            "Notifiarr connections failed: check protected runtime inputs (values suppressed)."
        )
