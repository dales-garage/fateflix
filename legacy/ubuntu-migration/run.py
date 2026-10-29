#!/usr/bin/env python3
"""Manual archive of a completed one-time Ubuntu migration, not routine operations.

Nothing runs without an explicit command and --confirm-legacy-operation. Review
the archived script's old host addresses and state assumptions before opting in.
This archive does not manage Xen Orchestra VM snapshots or schedule any job.
"""

import argparse
from pathlib import Path
import subprocess
import sys

COMMANDS = (
    "snapshot",
    "cutover-source",
    "migrate-native",
    "route-seerr",
    "restore",
    "configure-staging",
    "validate-state",
    "reassign-profiles",
    "extract-source-secrets",
    "import-pass",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-legacy-operation", action="store_true")
    parser.add_argument("command", choices=COMMANDS, nargs="?")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    if not args.confirm_legacy_operation:
        parser.error(
            "Archived operations require --confirm-legacy-operation before the command"
        )
    script = Path(__file__).resolve().parent / (args.command + ".py")
    subprocess.run([sys.executable, str(script), *args.arguments], check=True)


if __name__ == "__main__":
    main()
