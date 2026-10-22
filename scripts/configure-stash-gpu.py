#!/usr/bin/env python3
"""Set supported Stash YAML options before the container's writer starts."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import stat
import yaml


def configure(file, ffmpeg, ffprobe, enabled):
    os.umask(0o077)
    file = Path(file)
    info = file.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Stash configuration must be a regular file")
    original = file.read_text()
    data = yaml.safe_load(original)
    if not isinstance(data, dict) or not isinstance(data.get("ffmpeg", {}), dict):
        raise ValueError("Invalid Stash configuration mapping")
    if enabled and not all(Path(p).is_file() for p in (ffmpeg, ffprobe)):
        raise ValueError("Pinned FFmpeg tools are unavailable")
    data["ffmpeg_path"], data["ffprobe_path"] = ffmpeg, ffprobe
    data.setdefault("ffmpeg", {})["hardware_acceleration"] = enabled
    updated = yaml.safe_dump(data, sort_keys=False)
    mode = stat.S_IMODE(info.st_mode) & 0o600
    if original == updated and stat.S_IMODE(info.st_mode) == mode:
        return
    backup = file.with_name("config.before-gpu.yml")
    if not backup.exists():
        shutil.copyfile(file, backup)
        os.chown(backup, info.st_uid, info.st_gid)
        os.chmod(backup, 0o600)
    fd, pending = tempfile.mkstemp(prefix=".config-", dir=file.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(updated)
            f.flush()
            os.fsync(f.fileno())
        os.chown(pending, info.st_uid, info.st_gid)
        os.chmod(pending, mode)
        os.replace(pending, file)
        directory = os.open(file.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(pending).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        configure(*sys.argv[1:4], enabled=sys.argv[4] == "enabled")
    except (ValueError, OSError, yaml.YAMLError):
        sys.exit(
            "Stash GPU configuration failed; settings preserved, values suppressed."
        )
