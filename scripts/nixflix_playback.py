"""Bounded synthetic encode/decode diagnostics in the Stash container."""

import os
from pathlib import Path
import subprocess
import time

import nixflix_ops as ops

CONFIG = Path("/etc/nixflix/playback.json")


def command(args, seconds=20):
    # BusyBox timeout inside Alpine bounds the actual container process, too.
    subprocess.run(
        ["podman", "exec", "stash", "timeout", str(seconds), *args],
        check=True,
        timeout=seconds + 5,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def playback(if_changed=False):
    cfg = ops.read_json(CONFIG)
    with ops.lock("playback", blocking=False):
        if if_changed:
            try:
                previous = ops.read_json(ops.STATE / "playback.json")
                if previous.get("fingerprint") == cfg["fingerprint"] and previous.get(
                    "healthy"
                ):
                    return 0
            except (OSError, ValueError):
                pass
        checks = {}
        for codec, software in [
            ("h264", "libx264"),
            ("hevc", "libx265"),
            ("av1", "libsvtav1"),
        ]:
            target = f"/cache/.nixflix-playback-{os.getpid()}-{codec}.mkv"
            ffmpeg = cfg["ffmpeg"] if cfg["enabled"] else "/usr/bin/ffmpeg"
            common = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
            encode = common + (
                ["-vaapi_device", "/dev/dri/renderD128"] if cfg["enabled"] else []
            )
            encode += [
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=12",
                "-t",
                "1",
                "-an",
            ]
            if cfg["enabled"]:
                encode += ["-vf", "format=nv12,hwupload", "-c:v", codec + "_vaapi"]
            else:
                encode += ["-c:v", software, "-threads", "2"]
                if codec == "av1":
                    encode += ["-preset", "12", "-svtav1-params", "lp=2"]
            encode += [target]
            try:
                command(encode)
                decode = common + (
                    ["-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128"]
                    if cfg["enabled"]
                    else []
                )
                command(decode + ["-i", target, "-f", "null", "-"])
                checks[codec] = {"healthy": True}
            except (OSError, subprocess.SubprocessError) as error:
                checks[codec] = {"healthy": False, "error_type": type(error).__name__}
            finally:
                try:
                    command(["rm", "-f", target], seconds=5)
                except (OSError, subprocess.SubprocessError):
                    pass
        report = {
            "checked": time.time(),
            "fingerprint": cfg["fingerprint"],
            "mode": "gpu" if cfg["enabled"] else "software",
            "healthy": all(v["healthy"] for v in checks.values()),
            "checks": checks,
        }
        ops.write_json("playback.json", report)
        return 0 if report["healthy"] else 1
