#!/usr/bin/env python3
"""Migration only: run as root on the source Ubuntu machine, not the NixOS VM.
All declared source directories are required. Copy state using SQLite backup for
live databases; Plex uses its dated backups instead of the live library database.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

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


def require_source(source):
    if not source.is_dir():
        raise ValueError("Required migration source is not a directory: " + str(source))
    # os.walk otherwise suppresses an unreadable root just like a missing one.
    with os.scandir(source) as entries:
        next(entries, None)


def walk_error(error):
    raise error


def write_manifest(destination, manifest):
    fd, pending = tempfile.mkstemp(prefix=".snapshot-", dir=destination)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, destination / "snapshot.json")
        directory = os.open(destination, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(pending).unlink(missing_ok=True)


def resume_manifest(destination):
    path = destination / "snapshot.json"
    if destination.is_symlink() or not destination.is_dir() or path.is_symlink():
        raise ValueError("Resume requires a real snapshot directory and manifest")
    manifest = json.loads(path.read_text())
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("started"), str)
        or not manifest["started"]
        or not isinstance(manifest.get("services"), dict)
        or not set(manifest["services"]) <= set(SOURCES)
    ):
        raise ValueError("Invalid migration snapshot manifest")
    for name, record in manifest["services"].items():
        target = destination / name
        if (
            not isinstance(record, dict)
            or record.get("source") != SOURCES[name]
            or not isinstance(record.get("databases"), list)
            or not all(isinstance(item, dict) for item in record["databases"])
            or target.is_symlink()
            or not target.is_dir()
        ):
            raise ValueError("Invalid completed migration snapshot service: " + name)
    if "completed" in manifest and (
        not isinstance(manifest["completed"], str)
        or not manifest["completed"]
        or set(manifest["services"]) != set(SOURCES)
    ):
        raise ValueError("Completed snapshot does not contain every required service")
    return manifest


def snapshot(source, target, plex=False):
    require_source(source)
    records = []
    for directory, dirs, files in os.walk(
        source, followlinks=False, onerror=walk_error
    ):
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
        manifest = resume_manifest(args.destination)
        if "completed" in manifest:
            return
    else:
        manifest = {
            "started": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "services": {},
        }
    # No implicit optional sources: detect missing/unreadable pending services
    # before any copying. Completed, validated services need not still exist on
    # the source machine when resuming an interrupted migration snapshot.
    for name, source in SOURCES.items():
        if name not in manifest["services"]:
            require_source(Path(source))
    if not args.resume:
        args.destination.mkdir(parents=True, exist_ok=False, mode=0o700)
        write_manifest(args.destination, manifest)
    for name, source in SOURCES.items():
        if name in manifest["services"]:
            continue
        if (args.destination / name).exists():
            shutil.rmtree(args.destination / name)
        records = snapshot(Path(source), args.destination / name, plex=name == "plex")
        manifest["services"][name] = {"source": source, "databases": records}
        write_manifest(args.destination, manifest)
        print("Snapshotted " + name, flush=True)
    manifest["completed"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_manifest(args.destination, manifest)


if __name__ == "__main__":
    main()
