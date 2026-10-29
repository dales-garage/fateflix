#!/usr/bin/env python3
"""Compare restored libraries against protected snapshots without printing secrets."""

import argparse
import json
from pathlib import Path
import sqlite3

ARR = {
    "sonarr": ("sonarr.db", "Series"),
    "sonarr-4k": ("sonarr.db", "Series"),
    "radarr": ("radarr.db", "Movies"),
    "radarr-4k": ("radarr.db", "Movies"),
    "lidarr": ("lidarr.db", "Artists"),
}


def read(path, table):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Database validation failed")
        titles = db.execute(
            f"SELECT Id, Path, Monitored FROM {table} ORDER BY Id"
        ).fetchall()
        history = db.execute("SELECT COUNT(*) FROM History").fetchone()[0]
        return titles, history


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    a = p.parse_args()
    report = {}
    for name, (database, table) in ARR.items():
        before = read(a.snapshot / name / database, table)
        after = read(Path("/var/lib") / name / database, table)
        if before != after:
            raise RuntimeError(
                name + ": titles, paths, monitored flags or history differ"
            )
        report[name] = {"titles": len(after[0]), "history": after[1], "preserved": True}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
