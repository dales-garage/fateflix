#!/usr/bin/env python3
"""Assign an instance's titles to one existing profile, verify, then remove obsolete profiles.
Never submits commands, searches, renames or moveFiles requests.
"""

import argparse
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PROFILES = {
    "sonarr": (8990, "series", "WEB-1080p (Alternative)"),
    "sonarr-4k": (8989, "series", "WEB-2160p (Alternative)"),
    "radarr": (7879, "movie", "[SQP] SQP-1 (1080p)"),
    "radarr-4k": (7878, "movie", "[SQP] SQP-1 (2160p)"),
}


def migrate(call, endpoint, desired):
    profiles = call("GET", "qualityprofile")
    matches = [p for p in profiles if p["name"] == desired]
    if len(matches) != 1:
        raise ValueError("The exact managed profile must exist before reassignment")
    target = matches[0]["id"]
    titles = call("GET", endpoint)
    before = {t["id"]: (t.get("path"), t.get("monitored")) for t in titles}
    for title in titles:
        if title["qualityProfileId"] != target:
            updated = dict(title, qualityProfileId=target)
            call("PUT", f"{endpoint}/{title['id']}?moveFiles=false", updated)
    after = call("GET", endpoint)
    if before != {t["id"]: (t.get("path"), t.get("monitored")) for t in after} or any(
        t["qualityProfileId"] != target for t in after
    ):
        raise ValueError("Verification failed; no obsolete profiles were deleted")
    # Import lists also hold profile references. Preserve them while changing only
    # their profile selection; forceSave skips unreachable-provider validation in staging.
    lists = call("GET", "importlist")
    for item in lists:
        if item.get("qualityProfileId") not in (None, target):
            call(
                "PUT",
                f"importlist/{item['id']}?forceSave=true",
                dict(item, qualityProfileId=target),
            )
    if any(
        item.get("qualityProfileId") not in (None, target)
        for item in call("GET", "importlist")
    ):
        raise ValueError(
            "Import-list profile verification failed; obsolete profiles retained"
        )
    if endpoint == "movie":
        collections = call("GET", "collection")
        for collection in collections:
            if collection.get("qualityProfileId") != target:
                call(
                    "PUT",
                    f"collection/{collection['id']}",
                    dict(collection, qualityProfileId=target),
                )
        after_collections = call("GET", "collection")
        if any(c.get("qualityProfileId") != target for c in after_collections):
            raise ValueError(
                "Collection profile verification failed; obsolete profiles retained"
            )
        preserved = lambda items: {
            c["id"]: (c.get("monitored"), c.get("rootFolderPath")) for c in items
        }
        if preserved(collections) != preserved(after_collections):
            raise ValueError("Collection state changed; obsolete profiles retained")
    for profile in profiles:
        if profile["id"] != target:
            call("DELETE", f"qualityprofile/{profile['id']}")
    return len(after)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("instance", choices=PROFILES)
    args = p.parse_args()
    port, endpoint, profile = PROFILES[args.instance]
    key = Path("/var/lib/nixflix-secrets/current", args.instance).read_text().strip()

    def call(method, resource, payload=None):
        request = Request(
            f"http://127.0.0.1:{port}/api/v3/{resource}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"X-Api-Key": key, "Content-Type": "application/json"},
            method=method,
        )
        with urlopen(request, timeout=60) as response:
            data = response.read()
            return json.loads(data) if data else None

    try:
        count = migrate(call, endpoint, profile)
    except HTTPError as error:
        try:
            details = json.loads(error.read())
            fields = (
                [
                    d.get("propertyName", "") + ": " + d.get("errorMessage", "")
                    for d in details
                    if isinstance(d, dict)
                ]
                if isinstance(details, list)
                else (
                    [str(details.get("message", ""))]
                    if isinstance(details, dict)
                    else []
                )
            )
            print(
                ("HTTP " + str(error.code) + " " + "; ".join(fields)).replace(
                    key, "[redacted]"
                ),
                file=sys.stderr,
            )
        except (ValueError, TypeError):
            pass
        sys.exit(
            "Profile migration stopped after an API error; no searches or moves were requested."
        )
    except Exception:
        sys.exit(
            "Profile migration failed; inspect the instance before retrying. No searches or moves were requested."
        )
    print(f"{args.instance}: verified {count} titles on {profile}")


if __name__ == "__main__":
    main()
