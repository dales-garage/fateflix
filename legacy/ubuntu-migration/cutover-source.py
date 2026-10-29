#!/usr/bin/env python3
"""Freeze Ubuntu media writers and stream a protected, cold snapshot to nixflix.

Run from the workstation. No keys or Python interpreter are installed on Ubuntu.
Source containers and their original restart policies are retained for rollback.
"""

import argparse
import datetime
import json
import re
import shlex
import subprocess
from urllib.parse import urlencode
from urllib.request import urlopen

from configobj import ConfigObj
from snapshot import SOURCES

SSH = ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes"]
SOURCE = "drbrown@10.69.0.12"
TARGET = "marty@10.69.0.18"
CONTAINERS = [
    "sonarr2",
    "sonarr",
    "radarr2",
    "radarr",
    "lidarr",
    "prowlarr",
    "sabnzbd",
    "plex",
    "overseerr",
    "bazarr",
    "bazarr4k",
    "whisparr",
    "readarr",
    "mylar3",
    "tautulli",
    "audiobookshelf",
    "stash",
    "notifiarr",
    "ombi",
    "wizarr",
]
BASE = "/var/lib/nixflix-migration"


def remote(host, command, data=None):
    return subprocess.check_output(SSH + [host, command], input=data)


def save(path, value):
    remote(
        SOURCE,
        f"sudo -n tee {shlex.quote(path)} >/dev/null",
        (json.dumps(value, indent=2) + "\n").encode(),
    )


def inspect():
    # Never retrieve container environments or arguments containing tokens.
    raw = remote(
        SOURCE,
        "sudo -n docker inspect --format "
        + shlex.quote(
            "{{.Name}} {{.State.Running}} {{.HostConfig.RestartPolicy.Name}} {{.HostConfig.RestartPolicy.MaximumRetryCount}}"
        )
        + " "
        + " ".join(CONTAINERS),
    ).decode()
    return {
        name.lstrip("/"): dict(
            running=running == "true", restart=policy, retries=int(retries)
        )
        for name, running, policy, retries in (
            line.split() for line in raw.splitlines()
        )
    }


def require_stopped():
    if any(state["running"] for state in inspect().values()):
        raise RuntimeError(
            "A source media container is still running; snapshot aborted"
        )


def freeze(path):
    remote(SOURCE, f"sudo -n mkdir -m 700 {shlex.quote(path)}")
    state = inspect()
    save(path + "/source-containers.json", state)
    config = ConfigObj(
        remote(SOURCE, "sudo -n cat /docker/sabnzbd-config/sabnzbd.ini")
        .decode()
        .splitlines()
    )
    query = urlencode(
        dict(mode="pause", output="json", apikey=config["misc"]["api_key"])
    )
    try:
        with urlopen("http://10.69.0.12:8080/api?" + query, timeout=30) as response:
            if not json.load(response).get("status"):
                raise RuntimeError("SABnzbd did not acknowledge queue pause")
    except Exception:
        raise RuntimeError(
            "Could not pause source SABnzbd; credentials suppressed"
        ) from None
    names = " ".join(CONTAINERS)
    remote(SOURCE, "sudo -n docker update --restart=no " + names)
    remote(SOURCE, "sudo -n docker stop --time 120 " + names)
    require_stopped()
    save(
        path + "/freeze.json",
        {"frozen": datetime.datetime.now(datetime.timezone.utc).isoformat()},
    )
    print("Ubuntu media writers stopped; original restart policies saved.", flush=True)


def snapshot(path):
    remote(SOURCE, f"sudo -n test -f {shlex.quote(path + '/freeze.json')}")
    require_stopped()
    manifest = dict(
        started=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        method="cold-copy-current-databases-with-sidecars",
        services={},
    )
    for name, source in SOURCES.items():
        destination = path + "/" + name
        remote(SOURCE, f"sudo -n install -d -m 700 {shlex.quote(destination)}")
        # Preserve WAL/journal sidecars and symlinks in this stopped, consistent copy.
        command = [
            "sudo",
            "-n",
            "rsync",
            "-a",
            "--delete",
            "--exclude=*.pid",
            "--exclude=*.sock",
            "--exclude=Logs/",
            "--exclude=logs/",
            "--exclude=Crash Reports/",
        ]
        if name == "plex":
            command += ["--exclude=Cache/"]
        command += [source + "/", destination + "/"]
        remote(SOURCE, shlex.join(command))
        manifest["services"][name] = dict(source=source, databases=[])
        save(path + "/snapshot.json", manifest)
        print("Cold snapshot: " + name, flush=True)
    require_stopped()
    manifest["completed"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save(path + "/snapshot.json", manifest)


def transfer(path):
    require_stopped()
    manifest = json.loads(
        remote(SOURCE, f"sudo -n cat {shlex.quote(path + '/snapshot.json')}")
    )
    if not manifest.get("completed"):
        raise RuntimeError("Source snapshot incomplete")
    name = path.rsplit("/", 1)[1]
    remote(
        TARGET, f'test "$(hostname)" = nixflix && sudo -n test ! -e {shlex.quote(path)}'
    )
    reader = subprocess.Popen(
        SSH + [SOURCE, f"sudo -n tar -C {BASE} -cf - {name}"], stdout=subprocess.PIPE
    )
    writer = subprocess.run(
        SSH + [TARGET, f"sudo -n tar -C {BASE} -xpf -"], stdin=reader.stdout
    )
    reader.stdout.close()
    if reader.wait() or writer.returncode:
        raise RuntimeError(
            "Snapshot transfer failed; preserve partial destination for inspection"
        )
    require_stopped()
    print("Transferred protected snapshot to nixflix: " + path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "snapshot", "transfer", "all"])
    parser.add_argument(
        "name",
        help="Unique snapshot name beginning final-; never reuse a previous cutover",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"final-[a-zA-Z0-9_-]+", args.name):
        parser.error("invalid snapshot name")
    path = BASE + "/" + args.name
    for action in ("freeze", "snapshot", "transfer"):
        if args.action in (action, "all"):
            globals()[action](path)


if __name__ == "__main__":
    main()
