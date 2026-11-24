"""Age-backed vault initialization and lossless, non-destructive GPG migration."""

import argparse
import hmac
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def command(args, *, data=None, env=None):
    return subprocess.run(
        args, input=data, env=env, capture_output=True, check=True, timeout=60
    ).stdout


def locations():
    return (
        Path(os.environ.get("PASSAGE_DIR", str(Path.home() / ".passage/store"))),
        Path(
            os.environ.get(
                "PASSAGE_IDENTITIES_FILE", str(Path.home() / ".passage/identities")
            )
        ),
    )


def initialize(identity):
    identity.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not identity.exists():
        command(["age-keygen", "-o", str(identity)])
    stat = identity.stat()
    if identity.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise ValueError("Age identity must be a private file owned by this user")


def environment(store, identity):
    return dict(
        os.environ, PASSAGE_DIR=str(store), PASSAGE_IDENTITIES_FILE=str(identity)
    )


def read(entry, env):
    return command(["passage", "show", entry], env=env)


def write(entry, value, env):
    command(["passage", "insert", "--multiline", "--force", entry], data=value, env=env)
    if not hmac.compare_digest(read(entry, env), value):
        raise ValueError("Passage round-trip verification failed")


def import_values(values):
    if (
        not isinstance(values, dict)
        or not values
        or any(
            not isinstance(key, str)
            or not key.replace("_", "").isalnum()
            or not isinstance(value, str)
            or not value.strip()
            for key, value in values.items()
        )
    ):
        raise ValueError("Invalid credential input")
    os.umask(0o077)
    store, identity = locations()
    initialize(identity)
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = environment(store, identity)
    for key, value in values.items():
        write("secretspec/nixflix/default/" + key, value.encode(), env)


def migrate(legacy_pass):
    os.umask(0o077)
    source = Path(
        os.environ.get("PASSWORD_STORE_DIR", str(Path.home() / ".password-store"))
    )
    entries = sorted(
        p for p in source.rglob("*.gpg") if ".git" not in p.relative_to(source).parts
    )
    if not entries or any(p.is_symlink() for p in entries):
        raise ValueError("Expected a nonempty GPG vault without symlink entries")
    store, identity = locations()
    initialize(identity)
    store.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing = store.exists()
    stage = Path(tempfile.mkdtemp(prefix=".migration-", dir=store.parent))
    env = environment(store if existing else stage, identity)
    try:
        for path in entries:
            entry = path.relative_to(source).with_suffix("").as_posix()
            value = command([legacy_pass, "show", entry])
            if existing:
                if not hmac.compare_digest(read(entry, env), value):
                    raise ValueError(
                        "Existing age vault differs; neither vault was overwritten"
                    )
            else:
                write(entry, value, env)
        if not existing:
            # Publish only after every ciphertext has decrypted to the original bytes.
            os.rename(stage, store)
        return len(entries)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-pass",
        required=True,
        help="Absolute path to the original GPG pass executable",
    )
    args = parser.parse_args()
    if not Path(args.legacy_pass).is_absolute():
        parser.error("--legacy-pass must be an absolute executable path")
    try:
        count = migrate(args.legacy_pass)
    except (OSError, ValueError, subprocess.SubprocessError):
        sys.exit(
            "Passage migration failed; original GPG entries preserved; credential output suppressed."
        )
    print(
        f"Verified {count} age-encrypted entries; original GPG vault retained for rollback."
    )


if __name__ == "__main__":
    main()
