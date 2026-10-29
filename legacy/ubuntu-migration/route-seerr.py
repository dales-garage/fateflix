#!/usr/bin/env python3
"""Keep the existing Ubuntu tunnel's overseerr origin working after Seerr cutover.

Uses Node from the already installed Overseerr image as a temporary TCP relay.
The stopped source application is retained, with no access to the relay process.
"""

import argparse
import re
import shlex
import subprocess
from urllib.request import urlopen

SSH = ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "drbrown@10.69.0.12"]
RELAY = "nixflix-seerr-relay"
PROGRAM = """
const net = require('node:net');
net.createServer(client => {
  const upstream = net.connect(5055, '10.69.0.18');
  client.on('error', () => upstream.destroy());
  upstream.on('error', () => client.destroy());
  client.on('close', () => upstream.destroy());
  upstream.on('close', () => client.destroy());
  client.pipe(upstream).pipe(client);
}).listen(5055, '0.0.0.0');
"""


def remote(command):
    return subprocess.check_output(SSH + [shlex.join(command)], text=True).strip()


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    with urlopen("http://10.69.0.18:5055/api/v1/status", timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("Target Seerr is not ready")
    if (
        remote(
            [
                "sudo",
                "-n",
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                "overseerr",
            ]
        )
        != "false"
    ):
        raise RuntimeError("Stop source Overseerr before routing requests")
    image = remote(
        ["sudo", "-n", "docker", "inspect", "--format", "{{.Image}}", "overseerr"]
    )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise RuntimeError("Unexpected source image identity")
    names = remote(
        ["sudo", "-n", "docker", "ps", "-a", "--format", "{{.Names}}"]
    ).splitlines()
    if RELAY in names:
        raise RuntimeError("Relay already exists; inspect it before changing routing")
    # A stopped container still owns its network alias. Release it first.
    remote(["sudo", "-n", "docker", "network", "disconnect", "arrproxy", "overseerr"])
    try:
        remote(
            [
                "sudo",
                "-n",
                "docker",
                "run",
                "-d",
                "--name",
                RELAY,
                "--network",
                "arrproxy",
                "--network-alias",
                "overseerr",
                "--restart",
                "unless-stopped",
                "--read-only",
                "--user",
                "1000:1000",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--entrypoint",
                "node",
                image,
                "-e",
                PROGRAM,
            ]
        )
    except subprocess.CalledProcessError:
        subprocess.run(SSH + ["sudo -n docker rm -f " + RELAY], check=False)
        remote(
            [
                "sudo",
                "-n",
                "docker",
                "network",
                "connect",
                "--alias",
                "overseerr",
                "arrproxy",
                "overseerr",
            ]
        )
        raise
    print("Existing tunnel origin now relays to Seerr at 10.69.0.18:5055.")


if __name__ == "__main__":
    main()
