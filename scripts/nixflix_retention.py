"""Read Plex/Tautulli metadata only; never traverse media paths or mutate libraries."""

import configparser
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import nixflix_ops as ops


def summarize(item, watched, now):
    versions = item.get("Media", [])
    sizes = [
        sum(int(p.get("size", 0)) for p in media.get("Part", [])) for media in versions
    ]
    added = int(item.get("addedAt", 0))
    last = watched.get(str(item["ratingKey"]))
    return {
        "rating_key": str(item["ratingKey"]),
        "title": item.get("title"),
        "library_type": item.get("type"),
        "age_days": int((now - added) / 86400) if added else None,
        "watched": bool(item.get("viewCount", 0) or last),
        "last_watched": last or item.get("lastViewedAt"),
        "size_bytes": sum(sizes),
        "version_count": len(versions),
        "potential_alternative_bytes": sum(sizes) - min(sizes) if len(sizes) > 1 else 0,
    }


def retention(http):
    token = (
        ET.parse("/var/lib/plex/Plex Media Server/Preferences.xml")
        .getroot()
        .get("PlexOnlineToken")
    )
    headers = {"X-Plex-Token": token, "Accept": "application/json"}
    base = "http://127.0.0.1:32400"
    config = configparser.ConfigParser(interpolation=None)
    config.read("/var/lib/tautulli/config.ini")
    key = config["General"]["api_key"].strip('"')
    watched = {}
    now = time.time()
    # Paginated history avoids filesystem size probes and Tautulli media rescans.
    for start in range(0, 1000000, 1000):
        response = http(
            "http://127.0.0.1:8181/api/v2?"
            + urlencode(
                {"apikey": key, "cmd": "get_history", "start": start, "length": 1000}
            )
        )["response"]
        if response["result"] != "success":
            raise ValueError("Tautulli history unavailable")
        page = response["data"]["data"]
        for row in page:
            if float(row.get("watched_status", 0)) < 1:
                continue
            rating = str(row.get("rating_key"))
            watched[rating] = max(watched.get(rating, 0), int(row.get("date", 0)))
        if start + len(page) >= int(response["data"]["recordsFiltered"]):
            break
    else:
        raise ValueError("History exceeds report pagination limit")
    sections = http(base + "/library/sections", headers)["MediaContainer"].get(
        "Directory", []
    )
    items = []
    for section in sections:
        if section["type"] not in ("movie", "show"):
            continue
        kind = "4" if section["type"] == "show" else "1"
        for start in range(0, 1000000, 500):
            url = (
                base
                + "/library/sections/"
                + str(section["key"])
                + "/all?"
                + urlencode(
                    {
                        "type": kind,
                        "X-Plex-Container-Start": start,
                        "X-Plex-Container-Size": 500,
                    }
                )
            )
            page = http(url, headers)["MediaContainer"]
            for item in page.get("Metadata", []):
                row = summarize(item, watched, now)
                row["library"] = section.get("title")
                items.append(row)
            if start + int(page.get("size", 0)) >= int(
                page.get("totalSize", page.get("size", 0))
            ):
                break
        else:
            raise ValueError("Library exceeds report pagination limit")
    report = {
        "checked": now,
        "items": items,
        "potential_alternative_bytes": sum(
            i["potential_alternative_bytes"] for i in items
        ),
        "note": "Metadata estimates; alternatives require manual review. No deletion is performed.",
    }
    ops.write_json("retention.json", report)
    print(
        str(len(items))
        + " metadata rows written to "
        + str(ops.STATE / "retention.json")
    )
