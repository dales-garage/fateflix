#!/usr/bin/env python3
"""Prepare Seerr request/issue notifications while its writer is stopped."""

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import tempfile


def configure(settings, application_url, enabled=False):
    settings.setdefault("main", {})["applicationUrl"] = application_url
    payload = {
        "title": "Seerr: {{event}} — {{subject}}",
        "body": "{{requestedBy_username}}: {{subject}}\n{{message}}\nReview requests: "
        + application_url
        + "/requests",
        "type": "info",
        "tag": "requests",
    }
    # Seerr stores a base64-encoded JSON string containing the JSON template.
    encoded = base64.b64encode(json.dumps(json.dumps(payload)).encode()).decode()
    agents = settings.setdefault("notifications", {}).setdefault("agents", {})
    agents["webhook"] = {
        "enabled": enabled,
        "types": 4062,
        "options": {
            "webhookUrl": "http://127.0.0.1:8000/notify/media",
            "jsonPayload": encoded,
        },
    }
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--application-url", required=True)
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    original = args.file.read_text()
    settings = configure(json.loads(original), args.application_url, args.enable)
    result = json.dumps(settings, indent=2) + "\n"
    if result == original:
        return
    backup = args.file.with_name("settings.before-apprise.json")
    if not backup.exists():
        shutil.copyfile(args.file, backup)
        os.chmod(backup, 0o600)
    fd, pending = tempfile.mkstemp(prefix=".settings-", dir=args.file.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(result)
            f.flush()
            os.fsync(f.fileno())
        os.chown(pending, args.file.stat().st_uid, args.file.stat().st_gid)
        os.replace(pending, args.file)
    finally:
        Path(pending).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
