"""Local operations state; only the locked probe worker accesses the NAS."""

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

STATE = Path("/var/lib/nixflix-gitops")
CONFIG = Path("/etc/nixflix/operations.json")
READY = Path("/var/lib/nixflix-migration/ready")
BOOT = Path("/proc/sys/kernel/random/boot_id")


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(name, value):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix="." + name, dir=STATE)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, STATE / name)
    finally:
        Path(pending).unlink(missing_ok=True)


@contextmanager
def lock(name, blocking=True):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / (name + ".lock")).open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield


def fresh(value, max_age, now=None):
    age = (time.time() if now is None else now) - value.get("checked", 0)
    return 0 <= age < max_age and value.get("boot_id") == BOOT.read_text().strip()


def cached_probe():
    cfg = read_json(CONFIG)
    try:
        value = read_json(STATE / "capacity.json")
        if fresh(value, cfg["probeMaxAge"]):
            return value
    except (OSError, ValueError):
        pass
    return {"nas": {"status": "unknown"}, "root": {"status": "unknown"}}


def capacity(path, thresholds, inodes=True):
    fs = os.statvfs(path)
    available = fs.f_bavail * fs.f_frsize
    status = (
        "critical"
        if available < thresholds["critical"]
        else "warning" if available < thresholds["warning"] else "ok"
    )
    result = {"status": status, "available_bytes": available}
    # CIFS often synthesizes inode counts. Only use real, bounded local totals.
    if inodes and 0 < fs.f_files < 2**63 and 0 <= fs.f_favail <= fs.f_files:
        free = fs.f_favail / fs.f_files
        result["inode_free_fraction"] = free
        if free < 0.05:
            result["status"] = "critical"
        elif free < 0.10 and status == "ok":
            result["status"] = "warning"
    return result


def probe():
    # The descriptor remains held even if statvfs blocks uninterruptibly. Future
    # invocations cannot create a pile of workers against an unavailable SMB.
    try:
        with lock("probe", blocking=False):
            cfg = read_json(CONFIG)
            value = {"checked": time.time(), "boot_id": BOOT.read_text().strip()}
            try:
                value["root"] = capacity("/", cfg["root"])
            except OSError:
                value["root"] = {"status": "unknown"}
            # Publish root results before any potentially blocking NAS syscall.
            value["nas"] = {"status": "unknown"}
            write_json("capacity.json", value)
            try:
                mounts = json.loads(
                    subprocess.check_output(
                        [
                            "findmnt",
                            "--task",
                            "1",
                            "--json",
                            "--mountpoint",
                            cfg.get("storageRoot", "/data"),
                            "-o",
                            "FSTYPE,OPTIONS",
                        ],
                        timeout=5,
                    )
                )["filesystems"]
                mount = mounts[0]
                required_mode = cfg["nasMode"]
                if mount["fstype"] != "cifs" or required_mode not in mount[
                    "options"
                ].split(","):
                    raise ValueError("NAS mount mode")
                # Metadata access only. No enumeration, content scans or writes.
                os.stat(cfg.get("mediaRoot", "/data/media"))
                value["nas"] = capacity(
                    cfg.get("storageRoot", "/data"), cfg["nas"], inodes=False
                )
                value["nas"]["accessible"] = True
            except (
                OSError,
                ValueError,
                KeyError,
                IndexError,
                subprocess.SubprocessError,
            ):
                value["nas"] = {"status": "unknown", "accessible": False}
            # Keep the start timestamp: a slow probe cannot publish fresh results.
            write_json("capacity.json", value)
    except BlockingIOError:
        return


def held(name):
    return (STATE / "holds" / "all").exists() or (STATE / "holds" / name).exists()


def maintenance(action, name):
    cfg = read_json(CONFIG)
    if name != "all" and name not in cfg["services"]:
        raise ValueError("Unknown configured service")
    if os.geteuid() != 0:
        raise PermissionError("Maintenance holds require root")
    with lock("recovery"):
        directory = STATE / "holds"
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        path = directory / name
        if action == "hold":
            with path.open("w") as stream:
                stream.write(str(time.time()) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o600)
        else:
            path.unlink(missing_ok=True)
        fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def systemctl(*args):
    return (
        subprocess.run(
            ["systemctl", *args], timeout=10, check=False, stdout=subprocess.DEVNULL
        ).returncode
        == 0
    )


def nas_ready():
    return cached_probe()["nas"].get("accessible", False)


def recover():
    cfg = read_json(CONFIG)
    with lock("recovery", blocking=False):
        if held("all"):
            return
        # Mount and app reconciliation are independent. Never wait on SMB here.
        systemctl("start", "--no-block", cfg.get("mountUnit", "data.mount"))
        systemctl("start", "--no-block", "nixflix-capacity-probe.service")
        if not nas_ready():
            return
        systemctl("reset-failed", "nixflix-nas-ready.service")
        systemctl("start", "--no-block", "nixflix-nas-ready.service")
        for name in cfg["services"]:
            if (READY / name).exists() and not held(name):
                if not systemctl("is-active", "--quiet", name + ".service"):
                    systemctl("reset-failed", name + ".service")
                    systemctl("start", "--no-block", name + ".service")


def capacity_advisory(level):
    statuses = [v["status"] for k, v in cached_probe().items() if k in ("nas", "root")]
    if "unknown" in statuses:
        return False
    return not any(
        s == "critical" or (level == "warning" and s == "warning") for s in statuses
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["probe", "recover", "nas-ready", "hold", "release"]
    )
    parser.add_argument("service", nargs="?", default="all")
    args = parser.parse_args()
    os.umask(0o077)
    if args.action in ("hold", "release"):
        maintenance(args.action, args.service)
    elif args.action == "nas-ready":
        return 0 if nas_ready() else 1
    else:
        globals()[args.action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
