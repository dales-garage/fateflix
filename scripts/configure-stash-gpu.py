#!/usr/bin/env python3
"""Set supported Stash YAML options before the container's writer starts."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import yaml


def main():
    os.umask(0o077)
    file = Path(sys.argv[1])
    original = file.read_text()
    data = yaml.safe_load(original)
    data["ffmpeg_path"], data["ffprobe_path"] = sys.argv[2:4]
    data.setdefault("ffmpeg", {})["hardware_acceleration"] = True
    updated = yaml.safe_dump(data, sort_keys=False)
    if original == updated:
        return
    backup = file.with_name("config.before-gpu.yml")
    if not backup.exists():
        shutil.copyfile(file, backup)
        os.chmod(backup, 0o600)
    fd, pending = tempfile.mkstemp(prefix=".config-", dir=file.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(updated)
            f.flush()
            os.fsync(f.fileno())
        os.chown(pending, file.stat().st_uid, file.stat().st_gid)
        os.replace(pending, file)
    finally:
        Path(pending).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
