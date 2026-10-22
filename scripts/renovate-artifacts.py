#!/usr/bin/env python3
"""Generate Nix artifacts from Renovate's data using scripts from the PR base."""

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

REPO = "declarative-dale/nixflix"
VERSIONS = ".github/package-versions.json"
STATE = ".github/update-artifacts.json"
OUTPUTS = [
    STATE,
    "pkgs/notifiarr/default.nix",
    "pkgs/maintainerr/default.nix",
    "pkgs/maintainerr/missing-hashes.json",
    "modules/caddy/default.nix",
    "modules/navidrome/plugins/gen/*-plugin.nix",
    "modules/jellyfin/plugins/plugins.json",
]


def run(*args, capture=False):
    env = os.environ.copy()
    if args[0] == "nix":
        for key in ("GH_TOKEN", "GITHUB_TOKEN"):
            env.pop(key, None)
    return subprocess.run(
        args,
        check=True,
        text=True,
        env=env,
        stdout=subprocess.PIPE if capture else None,
    ).stdout


def read_ref(ref, path):
    mode = run("git", "ls-tree", ref, "--", path, capture=True).split()[0]
    if mode != "100644":
        raise ValueError("Expected a regular data file: " + path)
    return json.loads(run("git", "show", f"{ref}:{path}", capture=True))


def inputs():
    lock = json.loads(Path("flake.lock").read_text())
    return {
        "packages": json.loads(Path(VERSIONS).read_text()),
        "nixpkgs": lock["nodes"]["nixpkgs"]["locked"],
        "containers": json.loads(Path("hosts/nixflix/containers.json").read_text()),
    }


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def validate_versions(old, new):
    if set(new) != set(old):
        raise ValueError("Unexpected package keys")
    for name, value in new.items():
        if name == "caddyserver/replace-response":
            if not re.fullmatch(r"master@[a-f0-9]{40}", value):
                raise ValueError("Invalid Caddy revision")
        else:
            if not re.fullmatch(r"\d+\.\d+\.\d+", value):
                raise ValueError("Expected a stable release version")
            if tuple(map(int, value.split("."))) < tuple(
                map(int, old[name].split("."))
            ):
                raise ValueError("Refusing to downgrade " + name)


def validate_lock(old, new):
    # A lock refresh may advance existing pins, never substitute repositories or
    # execute a PR-provided flake. Channel/input edits need their own review.
    def identities(lock):
        lock = json.loads(json.dumps(lock))
        for node in lock["nodes"].values():
            for key in ("rev", "narHash", "lastModified"):
                node.get("locked", {}).pop(key, None)
        return lock

    if identities(old) != identities(new):
        raise ValueError(
            "Lock update changed input identities; manual artifact refresh required"
        )
    for node in new["nodes"].values():
        locked = node.get("locked", {})
        if "rev" in locked and not re.fullmatch(r"[a-f0-9]{40}", locked["rev"]):
            raise ValueError("Invalid locked revision")
        if "narHash" in locked and not re.fullmatch(
            r"sha256-[A-Za-z0-9+/]{43}=", locked["narHash"]
        ):
            raise ValueError("Invalid NAR hash")


def check():
    expected = fingerprint(inputs())
    if json.loads(Path(STATE).read_text()).get("inputs") != expected:
        raise ValueError(
            "Update artifacts pending: the Renovate helper must finish before CI builds"
        )
    for name, path in [
        ("Notifiarr/notifiarr", "pkgs/notifiarr/default.nix"),
        ("Maintainerr/Maintainerr", "pkgs/maintainerr/default.nix"),
    ]:
        version = re.search(r'version = "([^"]+)";', Path(path).read_text())[1]
        if version != inputs()["packages"][name]:
            raise ValueError("Package version is not synchronized: " + name)
    sha = inputs()["packages"]["caddyserver/replace-response"].split("@")[1]
    if sha[:12] not in Path("modules/caddy/default.nix").read_text():
        raise ValueError("Caddy revision is not synchronized")


def pr_info(number):
    pr = json.loads(run("gh", "api", f"repos/{REPO}/pulls/{number}", capture=True))
    if (
        pr["state"] != "open"
        or pr["user"]["login"] != "renovate[bot]"
        or pr["head"]["repo"]["full_name"] != REPO
        or pr["base"]["ref"] != "main"
        or not pr["head"]["ref"].startswith("renovate/")
    ):
        raise ValueError(
            "Only open, same-repository Renovate PRs targeting main are supported"
        )
    return pr


def commands(before, current, grouped_media=True):
    versions = current["packages"]
    result = []
    for name, command in [
        ("Notifiarr/notifiarr", ["python3", "pkgs/notifiarr/update.py"]),
        ("Maintainerr/Maintainerr", ["bash", "pkgs/maintainerr/update.sh"]),
    ]:
        if before["packages"][name] != versions[name]:
            result.append([*command, versions[name]])
    system_changed = before["nixpkgs"] != current["nixpkgs"]
    if (
        system_changed
        or before["packages"]["caddyserver/replace-response"]
        != versions["caddyserver/replace-response"]
    ):
        result.append(
            [
                "bash",
                "modules/caddy/update.sh",
                versions["caddyserver/replace-response"].split("@")[1],
                "--force",
            ]
        )
    if system_changed:
        result.append(["bash", "modules/navidrome/plugins/update.sh"])
    media_changed = before["containers"] != current["containers"] or any(
        before["packages"][name] != versions[name]
        for name in ("Notifiarr/notifiarr", "Maintainerr/Maintainerr")
    )
    if grouped_media and media_changed:
        result.append(["bash", "modules/jellyfin/plugins/update.sh", "--manifest-only"])
    return result


def generate(number, destination):
    pr = pr_info(number)
    head = pr["head"]["sha"]
    base = run("git", "rev-parse", "HEAD", capture=True).strip()
    if base != pr["base"]["sha"]:
        raise ValueError("Base advanced; rerun the helper against current main")
    run("git", "fetch", "origin", head)
    before = inputs()
    versions = read_ref(head, VERSIONS)
    validate_versions(before["packages"], versions)
    lock = read_ref(head, "flake.lock")
    validate_lock(json.loads(Path("flake.lock").read_text()), lock)
    containers = read_ref(head, "hosts/nixflix/containers.json")
    # Containers are fingerprinted only; no PR-provided container is executed.
    Path(VERSIONS).write_text(json.dumps(versions, indent=2) + "\n")
    Path("flake.lock").write_text(json.dumps(lock, indent=2) + "\n")
    Path("hosts/nixflix/containers.json").write_text(
        json.dumps(containers, indent=2) + "\n"
    )
    current = inputs()
    state = {"inputs": fingerprint(current)}
    if read_ref(head, STATE) == state:
        payload = {"pr": number, "head": head, "files": {}}
    else:
        for command in commands(
            before, current, pr["head"]["ref"] == "renovate/media-applications"
        ):
            run("nix", "develop", "--command", *command)
        Path(STATE).write_text(json.dumps(state, indent=2) + "\n")
        paths = sorted({str(p) for pattern in OUTPUTS for p in Path(".").glob(pattern)})
        nix_files = [p for p in paths if p.endswith(".nix")]
        if nix_files:
            run("nix", "fmt", "--", *nix_files)
        check()
        # Include deletions of generated files, but never unrelated files.
        tracked = run(
            "git", "ls-tree", "-r", "--name-only", head, capture=True
        ).splitlines()
        paths = sorted(set(paths) | {p for p in tracked if output_allowed(p)})
        files = {}
        for path in paths:
            value = Path(path).read_text() if Path(path).exists() else None
            previous = (
                run("git", "show", f"{head}:{path}", capture=True)
                if path in tracked
                else None
            )
            if value != previous:
                files[path] = value
        payload = {"pr": number, "head": head, "files": files}
    Path(destination).write_text(json.dumps(payload))
    print(f'Prepared {len(payload["files"])} generated files for PR #{number}')
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f'changed={str(bool(payload["files"])).lower()}\n')


def refresh(base):
    """Prepare a manually reviewed update without requiring a Renovate PR."""
    before = {
        "packages": read_ref(base, VERSIONS),
        "nixpkgs": read_ref(base, "flake.lock")["nodes"]["nixpkgs"]["locked"],
        "containers": read_ref(base, "hosts/nixflix/containers.json"),
    }
    current = inputs()
    validate_versions(before["packages"], current["packages"])
    for command in commands(before, current, grouped_media=False):
        run("nix", "develop", "--command", *command)
    paths = sorted(
        {
            str(p)
            for pattern in OUTPUTS
            for p in Path(".").glob(pattern)
            if p.suffix == ".nix"
        }
    )
    if paths:
        run("nix", "fmt", "--", *paths)
    Path(STATE).write_text(
        json.dumps({"inputs": fingerprint(current)}, indent=2) + "\n"
    )
    check()


def output_allowed(path):
    return ".." not in Path(path).parts and any(
        fnmatch.fnmatchcase(path, pattern) for pattern in OUTPUTS
    )


def publish(payload_path):
    payload = json.loads(Path(payload_path).read_text())
    if not payload["files"]:
        return
    if not all(output_allowed(p) for p in payload["files"]):
        raise ValueError("Generated files exceeded the allowlist")
    pr = pr_info(int(payload["pr"]))
    if pr["head"]["sha"] != payload["head"]:
        raise ValueError("PR changed during generation; refusing stale artifacts")
    head = pr["head"]["sha"]
    run("git", "fetch", "origin", head)
    run("git", "checkout", "--detach", head)
    for path, content in payload["files"].items():
        target = Path(path)
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
            raise ValueError("Generated path traverses a symlink")
        if content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    run("git", "add", "--", *payload["files"])
    run(
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "user.name=github-actions[bot]",
        "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit",
        "-m",
        "Refresh generated Nix update artifacts",
    )
    run("git", "push", "origin", f'HEAD:refs/heads/{pr["head"]["ref"]}')
    # GITHUB_TOKEN PR runs wait for approval; dispatch validated artifacts explicitly.
    run("gh", "workflow", "run", "ci.yml", "--repo", REPO, "--ref", pr["head"]["ref"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["check", "generate", "publish", "refresh"])
    parser.add_argument("--pr", type=int)
    parser.add_argument("--base")
    parser.add_argument("--payload", default="/tmp/renovate-artifacts.json")
    args = parser.parse_args()
    if args.mode == "check":
        check()
    elif args.mode == "refresh":
        if not args.base:
            parser.error("refresh requires an explicit --base commit")
        refresh(args.base)
    elif args.mode == "generate":
        generate(args.pr, args.payload)
    else:
        publish(args.payload)


if __name__ == "__main__":
    main()
