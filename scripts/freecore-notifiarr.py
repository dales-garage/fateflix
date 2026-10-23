#!/usr/bin/env python3
"""Forward FreeCORE's local alert feed to Notifiarr; install on the NAS."""

import argparse
from contextlib import contextmanager
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

LEVELS = {
    name: i
    for i, name in enumerate(
        ("INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"), 1
    )
}
MAX_PENDING = 1000


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


def private_json(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise ValueError("private file ownership/mode")
    return json.loads(path.read_text())


def validate_config(cfg):
    url = urlsplit(cfg["webhook"])
    if (
        url.scheme != "https"
        or url.netloc != "notifiarr.com"
        or not re.fullmatch(
            r"/api/v1/notification/passthrough/[A-Za-z0-9_-]+/?", url.path
        )
        or url.query
        or url.fragment
    ):
        raise ValueError("Notifiarr Passthrough webhook URL required")
    if not re.fullmatch(r"[1-9][0-9]{14,21}", str(cfg["channel"])):
        raise ValueError("numeric Discord channel ID required")
    if cfg.get("minimum", "WARNING") not in LEVELS:
        raise ValueError("unknown minimum alert level")
    if not isinstance(cfg["hostname"], str) or not cfg["hostname"].strip():
        raise ValueError("hostname required")


@contextmanager
def lock(folder):
    with (folder / "bridge.lock").open("a") as stream:
        os.fchmod(stream.fileno(), 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield stream.fileno()


def normalize(alerts):
    if not isinstance(alerts, list):
        raise ValueError("invalid alert feed")
    result = {}
    for item in alerts:
        identifier = str(item.get("id") or item.get("uuid") or "")
        level = item.get("level")
        if not identifier or identifier in result or level not in LEVELS:
            raise ValueError("invalid alert record")
        result[identifier] = {
            "level": level,
            "klass": str(item.get("klass", "System alert"))[:150],
            "formatted": str(item.get("formatted", "System alert"))[:3500],
            "dismissed": bool(item.get("dismissed")),
        }
    return result


def reconcile(state, alerts, minimum):
    # Validate the entire feed before treating any absent ID as cleared.
    current = normalize(alerts)
    active = {k: v for k, v in state["active"].items() if k in current}
    pending = list(state["pending"])
    for identifier, item in current.items():
        if item["dismissed"] or LEVELS[item["level"]] < LEVELS[minimum]:
            continue
        old = state["active"].get(identifier)
        if old is None or LEVELS[item["level"]] > LEVELS[old["level"]]:
            pending.append(
                {
                    "event": uuid.uuid4().hex,
                    "status": "firing",
                    "id": identifier,
                    "alert": item,
                }
            )
        active[identifier] = item
    for identifier, item in state["active"].items():
        if identifier not in current:
            pending.append(
                {
                    "event": uuid.uuid4().hex,
                    "status": "cleared",
                    "id": identifier,
                    "alert": item,
                }
            )
    if len(pending) > MAX_PENDING:
        raise ValueError("delivery queue full")
    return dict(state, active=active, pending=pending, last_poll=time.time())


def payload(cfg, event):
    item = event["alert"]
    cleared = event["status"] == "cleared"
    title = "Alert cleared" if cleared else item["level"] + " alert"
    description = item["formatted"]
    if cleared:
        description = "No longer reported by FreeCORE:\n" + description
    return {
        "notification": {"name": "FreeCORE", "event": event["event"], "update": True},
        "discord": {
            "color": (
                "2ECC71"
                if cleared
                else "E74C3C" if LEVELS[item["level"]] >= 4 else "F39C12"
            ),
            "ids": {"channel": int(cfg["channel"])},
            "text": {
                "title": (cfg["hostname"] + ": " + title)[:250],
                "description": description[:4000],
                "footer": (item["klass"] + " | " + event["id"])[:500],
            },
        },
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def deliver(cfg, event):
    req = urllib.request.Request(
        cfg["webhook"],
        data=json.dumps(payload(cfg, event)).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as response:
        result = json.loads(response.read(1048576))
    if (
        result.get("result") != "success"
        and result.get("details", {}).get("response")
        != "Pass through payload processed."
    ):
        raise ValueError("notification was not acknowledged")


def drain(cfg, state, path, sender=None):
    sender = sender or deliver
    for _ in range(min(4, len(state["pending"]))):
        sender(cfg, state["pending"][0])
        state["pending"].pop(0)
        state["last_delivery"] = time.time()
        atomic_json(path, state)


def run(cfg, state_path, lock_fd):
    state = (
        private_json(state_path)
        if state_path.exists()
        else {"version": 1, "active": {}, "pending": []}
    )
    if (
        state.get("version") != 1
        or not isinstance(state.get("active"), dict)
        or not isinstance(state.get("pending"), list)
    ):
        raise ValueError("invalid state; preserve it for review")
    # Keep the lock in a blocked child so cron cannot accumulate workers.
    try:
        ready = subprocess.check_output(
            [shutil.which("midclt") or "/usr/local/bin/midclt", "call", "system.ready"],
            timeout=5,
            stderr=subprocess.DEVNULL,
            pass_fds=(lock_fd,),
        )
        if json.loads(ready) is not True:
            raise ValueError("middleware not ready; preserve current alerts")
        output = subprocess.check_output(
            [shutil.which("midclt") or "/usr/local/bin/midclt", "call", "alert.list"],
            timeout=15,
            stderr=subprocess.DEVNULL,
            pass_fds=(lock_fd,),
        )
        state = reconcile(state, json.loads(output), cfg.get("minimum", "WARNING"))
        atomic_json(state_path, state)
    except Exception:
        # Previously queued notifications may still be delivered during a feed outage.
        drain(cfg, state, state_path)
        raise
    drain(cfg, state, state_path)
    print(
        json.dumps(
            {
                "active": len(state["active"]),
                "pending": len(state["pending"]),
                "last_poll": state.get("last_poll"),
                "last_delivery": state.get("last_delivery"),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "run", "test", "status"])
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().with_name("notifiarr.json"),
    )
    args = parser.parse_args()
    os.umask(0o077)
    folder = args.config.parent
    if (
        folder.is_symlink()
        or folder.stat().st_uid != os.geteuid()
        or stat.S_IMODE(folder.stat().st_mode) & 0o077
    ):
        raise ValueError("use a private directory owned by the current user")
    with lock(folder) as fd:
        state_path = folder / "state.json"
        if args.action == "init":
            if args.config.exists():
                raise ValueError("configuration already exists; edit its private file")
            cfg = {
                "webhook": getpass.getpass(
                    "Notifiarr Passthrough webhook URL (hidden): "
                ).strip(),
                "channel": input("Existing Discord errors channel ID: ").strip(),
                "hostname": socket.gethostname(),
                "minimum": "WARNING",
            }
            validate_config(cfg)
            atomic_json(args.config, cfg)
            print(
                "Saved private configuration. Run test, then run before enabling cron."
            )
            return
        cfg = private_json(args.config)
        validate_config(cfg)
        if args.action == "test":
            deliver(
                cfg,
                {
                    "event": uuid.uuid4().hex,
                    "status": "firing",
                    "id": "TEST",
                    "alert": {
                        "level": "WARNING",
                        "klass": "Delivery test",
                        "formatted": "TEST ONLY: FreeCORE to Notifiarr delivery works. No real disk fault is being reported.",
                    },
                },
            )
            print(
                "Test accepted by Notifiarr; verify it arrived in the errors channel."
            )
        elif args.action == "status":
            state = private_json(state_path) if state_path.exists() else {}
            print(
                json.dumps(
                    {
                        "active": len(state.get("active", {})),
                        "pending": len(state.get("pending", [])),
                        "last_poll": state.get("last_poll"),
                        "last_delivery": state.get("last_delivery"),
                    }
                )
            )
        else:
            run(cfg, state_path, fd)


if __name__ == "__main__":
    try:
        main()
    except BlockingIOError:
        sys.exit(0)
    except Exception as error:
        # Request exceptions may contain the secret webhook URL.
        sys.exit(
            "FreeCORE alert bridge failed ("
            + type(error).__name__
            + "); values suppressed. Pending alerts are retained."
        )
