#!/usr/bin/env python3
"""Run as root on Ubuntu. Copy state, using SQLite backup for live databases.
Plex uses its dated database backups instead of the live library database.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3

SOURCES = {
    "sonarr": "/docker/sonarr2-config",
    "sonarr-4k": "/docker/sonarr-config",
    "radarr": "/docker/radarr2-config",
    "radarr-4k": "/docker/radarr-config",
    "lidarr": "/docker/lidarr-config",
    "prowlarr": "/docker/prowlarr-config",
    "sabnzbd": "/docker/sabnzbd-config",
    "plex": "/docker/plex-config/Library/Application Support",
    "seerr": "/docker/overseerr-config",
    "bazarr": "/srv/ezarr-hotio/bazarr-config",
    "bazarr-4k": "/srv/ezarr-hotio/bazarr4k-config",
    "whisparr": "/srv/ezarr-hotio/whisparr-config",
    "readarr": "/docker/readarr-config",
    "mylar3": "/docker/mylar-config",
    "notifiarr": "/docker/notifiarr-config",
    "tautulli": "/docker/tautulli-config",
    "audiobookshelf": "/docker/audiobookshelf-config",
    "audiobookshelf-metadata": "/data/metadata",
    "stash": "/opt/appdata/stash",
    "archive-ombi": "/opt/appdata/ombi",
    "archive-wizarr": "/opt/appdata/config",
}


def snapshot(source, target, plex=False):
    records = []
    for directory, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [
            d
            for d in dirs
            if d not in ("logs", "Logs", "Cache", "cache", "Crash Reports")
        ]
        rel = Path(directory).relative_to(source)
        dest = target / rel
        dest.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in files:
            src = Path(directory) / name
            dst = dest / name
            if src.is_symlink() or name.endswith(
                ("-wal", "-shm", "-journal", ".pid", ".sock")
            ):
                continue
            if not src.is_file():
                continue
            if plex and name in (
                "com.plexapp.plugins.library.db",
                "com.plexapp.plugins.library.blobs.db",
            ):
                backups = sorted(
                    p for p in src.parent.glob(name + "-????-??-??") if p.is_file()
                )
                if not backups:
                    raise RuntimeError("Plex has no dated backup for " + name)
                chosen = backups[-1]
                shutil.copy2(chosen, dst)
                records.append(
                    {
                        "file": str(rel / name),
                        "method": "plex-dated-backup",
                        "source": chosen.name,
                    }
                )
                continue
            with src.open("rb") as f:
                sqlite = f.read(16) == b"SQLite format 3\x00"
            if sqlite and not plex:
                with sqlite3.connect(
                    src.as_uri() + "?mode=ro", uri=True, timeout=60
                ) as db:
                    with sqlite3.connect(dst) as out:
                        db.backup(out, pages=1024, sleep=0.1)
                        try:
                            if out.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                                raise RuntimeError(
                                    "SQLite validation failed: " + str(src)
                                )
                        except sqlite3.DatabaseError as error:
                            if "syntax error" not in str(error):
                                raise
                            records.append(
                                {
                                    "file": str(rel / name),
                                    "validation": "requires-newer-sqlite-on-target",
                                }
                            )
                records.append(
                    {
                        "file": str(rel / name),
                        "method": "sqlite-backup",
                        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }
                )
            else:
                try:
                    shutil.copy2(src, dst)
                except FileNotFoundError:
                    # A cache/log rotation is not an application database snapshot.
                    if name.endswith((".log", ".log.1")):
                        continue
                    raise
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run as root")
    os.umask(0o077)
    if args.resume:
        manifest = json.loads((args.destination / "snapshot.json").read_text())
    else:
        args.destination.mkdir(parents=True, exist_ok=False, mode=0o700)
        manifest = {
            "started": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "services": {},
        }
    for name, source in SOURCES.items():
        if name in manifest["services"]:
            continue
        if (args.destination / name).exists():
            shutil.rmtree(args.destination / name)
        records = snapshot(Path(source), args.destination / name, plex=name == "plex")
        manifest["services"][name] = {"source": source, "databases": records}
        (args.destination / "snapshot.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
        print("Snapshotted " + name, flush=True)
    manifest["completed"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (args.destination / "snapshot.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
