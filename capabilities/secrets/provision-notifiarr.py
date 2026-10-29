#!/usr/bin/env python3
"""Resolve a Notifiarr key from SecretSpec, or install it from a private pipe."""

from role import installed_role

import os
from pathlib import Path
import re
import fcntl
import stat
import sys
import tempfile


def validate(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", value
    ):
        raise ValueError("Invalid API key")


def install_locked(value, directory, directory_fd):
    target = directory / "notifiarr-api-key"
    try:
        previous = target.lstat()
    except FileNotFoundError:
        previous = None
    if previous is not None:
        if not stat.S_ISREG(previous.st_mode) or previous.st_uid != os.geteuid():
            raise ValueError("Unsafe credential file")
        if (
            previous.st_gid == os.getegid()
            and stat.S_IMODE(previous.st_mode) == 0o600
            and target.read_bytes() == value.encode()
        ):
            return
    fd, pending = tempfile.mkstemp(dir=directory, prefix=".notifiarr-")
    backup = None
    published = False
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if previous is not None:
            backup_fd, name = tempfile.mkstemp(dir=directory, prefix=".notifiarr-")
            os.close(backup_fd)
            backup = Path(name)
            backup.unlink()
            os.link(target, backup, follow_symlinks=False)
            os.fsync(directory_fd)
        try:
            os.replace(pending, target)
            published = True
            os.fsync(directory_fd)
        except BaseException:
            if published:
                if backup is None:
                    target.unlink()
                else:
                    os.replace(backup, target)
                    backup = None
                os.fsync(directory_fd)
            raise
        if backup is not None:
            backup.unlink()
            backup = None
            os.fsync(directory_fd)
    finally:
        Path(pending).unlink(missing_ok=True)
        # If rollback itself failed, retain the private previous-key link for
        # recovery instead of deleting the only remaining copy of the old key.
        if backup is not None and not published:
            backup.unlink(missing_ok=True)


def install(value, directory):
    validate(value)
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_gid != os.getegid()
    ):
        raise ValueError("Unsafe credential directory")
    directory.chmod(0o700)
    directory_fd = os.open(directory, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
        fd = os.open(
            directory / ".notifiarr.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "a") as lock:
            info = os.fstat(lock.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_gid != os.getegid()
            ):
                raise ValueError("Unsafe credential lock")
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            install_locked(value, directory, directory_fd)
    finally:
        os.close(directory_fd)


def main():
    installed_role(production_only=True)
    os.umask(0o077)
    action = sys.argv[1]
    value = (
        os.environ.get("NOTIFIARR_API_KEY", "")
        if action == "emit"
        else sys.stdin.read()
    ).strip()
    validate(value)
    if action == "emit":
        sys.stdout.write(value)
        return
    if action != "install" or os.geteuid() != 0:
        raise ValueError("Installer requires root")
    install(value, Path("/var/lib/nixflix-secrets"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit("Notifiarr secret provisioning failed (values suppressed).")
