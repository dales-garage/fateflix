#!/usr/bin/env python3
"""Read-only live checks and secret-free deployment status for Comin/Notifiarr."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import time
import tomllib
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

STATE = Path("/var/lib/nixflix-gitops")


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(name, value):
    STATE.mkdir(mode=0o700, exist_ok=True)
    target = STATE / name
    tmp = target.with_suffix(".tmp-" + str(os.getpid()))
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.replace(target)


def http(url, headers=None, probe=False):
    try:
        with urlopen(Request(url, headers=headers or {}), timeout=10) as response:
            return response.status if probe else json.load(response)
    except HTTPError as error:
        if probe and error.code in (401, 403):
            return error.code
        raise


def active(unit):
    subprocess.run(["systemctl", "is-active", "--quiet", unit], check=True)


def arr(name, port):
    key = ET.parse(f"/var/lib/{name}/config.xml").findtext("ApiKey")
    version = "v1" if name in ("lidarr", "prowlarr", "readarr") else "v3"
    base = f"http://127.0.0.1:{port}/api/{version}"
    headers = {"X-Api-Key": key}
    http(base + "/system/status", headers)
    connections = http(base + "/notification", headers)
    if not any(c.get("implementation") == "Notifiarr" for c in connections):
        raise ValueError("Notifiarr connection missing")


def service(name, port):
    active(
        "podman-" + name
        if name in ("mylar3", "stash")
        else "homepage-dashboard" if name == "homepage" else name
    )
    http(f"http://127.0.0.1:{port}/", probe=True)
    if name in (
        "sonarr",
        "sonarr-4k",
        "radarr",
        "radarr-4k",
        "lidarr",
        "prowlarr",
        "readarr",
        "whisparr",
    ):
        arr(name, port)


def nas():
    mounts = json.loads(
        subprocess.check_output(
            ["findmnt", "--json", "--mountpoint", "/data", "-o", "FSTYPE,OPTIONS"]
        )
    )
    mount = mounts["filesystems"][0]
    assert mount["fstype"] == "cifs" and "rw" in mount["options"].split(",")


def credentials():
    paths = list(Path("/var/lib/nixflix-secrets/current").iterdir())
    paths.append(Path("/var/lib/nixflix-secrets/notifiarr-api-key"))
    assert len(paths) > 1
    for path in paths:
        stat = path.stat()
        assert stat.st_uid == 0 and not stat.st_mode & 0o077


def notifiarr():
    active("notifiarr")
    http("http://127.0.0.1:5454/", probe=True)
    cfg = tomllib.loads(Path("/run/notifiarr/notifiarr.conf").read_text())
    for name in (
        "sonarr",
        "radarr",
        "lidarr",
        "prowlarr",
        "readarr",
        "sabnzbd",
        "plex",
        "tautulli",
    ):
        assert cfg.get(name), name
    status = subprocess.check_output(
        ["systemctl", "show", "notifiarr-connections", "-p", "Result", "--value"],
        text=True,
    ).strip()
    assert status == "success"
    timestamp = subprocess.check_output(
        [
            "systemctl",
            "show",
            "notifiarr-connections",
            "-p",
            "ExecMainExitTimestampMonotonic",
            "--value",
        ],
        text=True,
    ).strip()
    assert int(timestamp) > 0


def seerr():
    key = read_json("/var/lib/seerr/settings.json")["main"]["apiKey"]
    cfg = http(
        "http://127.0.0.1:5055/api/v1/settings/notifications/webhook",
        {"X-Api-Key": key},
    )
    assert cfg["enabled"] and cfg["options"]["webhookUrl"].startswith(
        "https://notifiarr.com/api/v1/notification/seerr/"
    )


def plex():
    token = (
        ET.parse("/var/lib/plex/Plex Media Server/Preferences.xml")
        .getroot()
        .get("PlexOnlineToken")
    )
    http(
        "http://127.0.0.1:32400/library/sections",
        {"X-Plex-Token": token, "Accept": "application/json"},
    )


def sabnzbd():
    key = Path("/var/lib/nixflix-secrets/current/sabnzbd").read_text().strip()
    value = http(
        "http://127.0.0.1:8080/api?"
        + urlencode({"mode": "queue", "output": "json", "apikey": key})
    )
    assert "queue" in value


def networking():
    assert Path("/etc/nixflix/mode").read_text().strip() == "production"
    active("sshd")
    active("xen-guest-agent")
    # Exercise the deployed reverse proxy and its host routing, not just open ports.
    key = ET.parse("/var/lib/sonarr/config.xml").findtext("ApiKey")
    status = http(
        "http://127.0.0.1/api/v3/system/status",
        {"Host": "sonarr.vm.internal", "X-Api-Key": key},
    )
    assert status.get("appName") == "Sonarr"


def run_check(item):
    name, check = item
    try:
        check()
        return name, {"healthy": True}
    except Exception as error:
        # Exception strings can contain credential-bearing URLs: never publish them.
        return name, {"healthy": False, "error_type": type(error).__name__}


def check():
    services = read_json("/etc/nixflix/gitops-services.json")["services"]
    jobs = [
        (name, lambda n=name, p=port: service(n, p))
        for name, port in services.items()
        if name != "seeme"
    ]
    jobs += [
        ("nas", nas),
        ("credentials", credentials),
        ("networking", networking),
        ("notifiarr", notifiarr),
        ("seerr-webhook", seerr),
        ("plex-api", plex),
        ("sabnzbd-api", sabnzbd),
        ("comin", lambda: active("comin")),
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        checks = dict(executor.map(run_check, jobs))
    report = {
        "checked": time.time(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "system": os.path.realpath("/run/current-system"),
        "healthy": all(c["healthy"] for c in checks.values()),
        "checks": checks,
    }
    write_json("health.json", report)
    print(json.dumps(report))
    return 0 if report["healthy"] else 1


def hook():
    phase, status = os.environ["COMIN_PHASE"], os.environ["COMIN_STATUS"]
    event = {
        "sha": os.environ["COMIN_GIT_SHA"],
        "phase": phase,
        "status": status,
        "checked": time.time(),
    }
    write_json(phase + ".json", event)
    if phase == "deploy" and status == "done":
        event["system"] = os.path.realpath("/run/current-system")
        write_json("deployed.json", event)


def healthy(report, build, deploy, now, boot_id, system):
    return (
        report.get("healthy", False)
        and now - report["checked"] < 900
        and report.get("boot_id") == boot_id
        and report.get("system") == system
        and build.get("status") != "failed"
        and deploy.get("status") != "failed"
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        try:
            report = read_json(STATE / "health.json")
            events = [
                (
                    read_json(STATE / (p + ".json"))
                    if (STATE / (p + ".json")).exists()
                    else {}
                )
                for p in ("build", "deploy")
            ]
            ok = healthy(
                report,
                *events,
                time.time(),
                Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                os.path.realpath("/run/current-system"),
            )
        except (OSError, ValueError, KeyError):
            ok = False
        self.send_response(200 if ok else 503)
        self.end_headers()
        self.wfile.write(b"healthy\n" if ok else b"unhealthy\n")

    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "hook", "serve"])
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "hook":
        hook()
    elif args.action == "check":
        return check()
    else:
        HTTPServer(("127.0.0.1", 9199), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
