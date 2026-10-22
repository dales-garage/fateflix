"""Bounded synthetic encode/decode diagnostics in the Stash container."""

import os
from pathlib import Path
import subprocess
import time

import nixflix_ops as ops

CONFIG = Path("/etc/nixflix/playback.json")
PROBE_VERSION = 2


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
                if (
                    previous.get("probe_version") == PROBE_VERSION
                    and previous.get("fingerprint") == cfg["fingerprint"]
                    and previous.get("healthy")
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
            hardware_encode = cfg["enabled"] and codec != "av1"
            encode = common + (
                ["-vaapi_device", "/dev/dri/renderD128"] if hardware_encode else []
            )
            encode += [
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x192:rate=12",
                "-t",
                "1",
                "-an",
            ]
            if hardware_encode:
                encode += ["-vf", "format=nv12,hwupload", "-c:v", codec + "_vaapi"]
            else:
                encode += ["-c:v", software, "-threads", "2"]
                if codec == "av1":
                    # Rocket Lake decodes AV1 but cannot encode it. Generate a
                    # bounded 10-bit fixture in software to test the playback path.
                    encode += [
                        "-pix_fmt",
                        "yuv420p10le",
                        "-preset",
                        "12",
                        "-svtav1-params",
                        "lp=2",
                    ]
            encode += [target]
            result = {
                "healthy": False,
                "encode_mode": "gpu" if hardware_encode else "software",
                "decode_mode": "gpu" if cfg["enabled"] else "software",
            }
            stage = "encode"
            try:
                command(encode)
                stage = "decode"
                decode = common[:]
                if cfg["enabled"]:
                    decode += [
                        "-hwaccel",
                        "vaapi",
                        "-hwaccel_device",
                        "/dev/dri/renderD128",
                        "-hwaccel_output_format",
                        "vaapi",
                    ]
                    if codec == "av1":
                        # libdav1d is often the default and cannot use VA-API.
                        decode += ["-c:v", "av1"]
                decode += ["-i", target]
                if cfg["enabled"]:
                    # Requiring a hardware-frame download makes silent software
                    # fallback fail instead of reporting a GPU success.
                    pixel_format = "p010le" if codec == "av1" else "nv12"
                    decode += ["-vf", "hwdownload,format=" + pixel_format]
                command(decode + ["-f", "null", "-"])
                result["healthy"] = True
            except (OSError, subprocess.SubprocessError) as error:
                result.update(stage=stage, error_type=type(error).__name__)
            finally:
                checks[codec] = result
                try:
                    command(["rm", "-f", target], seconds=5)
                except (OSError, subprocess.SubprocessError):
                    pass
        report = {
            "checked": time.time(),
            "probe_version": PROBE_VERSION,
            "fingerprint": cfg["fingerprint"],
            "mode": "gpu" if cfg["enabled"] else "software",
            "healthy": all(v["healthy"] for v in checks.values()),
            "checks": checks,
        }
        ops.write_json("playback.json", report)
        return 0 if report["healthy"] else 1
