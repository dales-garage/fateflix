#!/usr/bin/env python3
"""Publish one reviewed PR per updater; never write to the production branch."""

import argparse
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

UPDATERS = {
    "notifiarr": (
        ["python3", "pkgs/notifiarr/update.py"],
        ["pkgs/notifiarr/default.nix"],
    ),
    "maintainerr": (
        ["bash", "pkgs/maintainerr/update.sh"],
        ["pkgs/maintainerr/default.nix", "pkgs/maintainerr/missing-hashes.json"],
    ),
    "caddy": (
        ["bash", "modules/_integrations/nixflix/compat/modules/caddy/update.sh"],
        ["modules/_integrations/nixflix/compat/modules/caddy/default.nix"],
    ),
    "jellyfin-plugins": (
        [
            "bash",
            "modules/_integrations/nixflix/compat/modules/jellyfin/plugins/update.sh",
            "--manifest-only",
        ],
        ["modules/_integrations/nixflix/compat/modules/jellyfin/plugins/plugins.json"],
    ),
    "navidrome-plugins": (
        [
            "bash",
            "modules/_integrations/nixflix/compat/modules/navidrome/plugins/update.sh",
        ],
        [
            "modules/_integrations/nixflix/compat/modules/navidrome/plugins/gen/*-plugin.nix"
        ],
    ),
}


def run(*args, capture=False, check=True):
    return subprocess.run(
        args, check=check, text=True, stdout=subprocess.PIPE if capture else None
    )


def allowed_changes(paths, patterns):
    return all(
        any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        for path in paths
    )


def changed_files():
    tracked = run(
        "git", "diff", "--name-only", "-z", "HEAD", capture=True
    ).stdout.split("\0")
    new = run(
        "git", "ls-files", "--others", "--exclude-standard", "-z", capture=True
    ).stdout.split("\0")
    return sorted(set(filter(None, tracked + new)))


def formatted_changes(patterns):
    changed = changed_files()
    if not allowed_changes(changed, patterns):
        raise RuntimeError(
            "Updater changed files outside its allowlist: " + ", ".join(changed)
        )
    nix_files = [p for p in changed if p.endswith(".nix") and Path(p).exists()]
    if nix_files:
        run("nix", "fmt", "--", *nix_files)
        run("nix", "fmt", "--", "--no-cache", "--fail-on-change", *nix_files)
    changed = changed_files()
    if not allowed_changes(changed, patterns):
        raise RuntimeError("Formatter changed files outside the updater allowlist")
    return changed


def sync_upstream():
    before = Path("flake.lock").read_bytes()
    run("nix", "flake", "update", "nixflix")
    return before != Path("flake.lock").read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["upstream", *UPDATERS])
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    if repository != "declarative-dale/nixflix":
        parser.error("This publisher is scoped to declarative-dale/nixflix")
    if args.kind == "jellyfin-plugins":
        # Only the ABI-aware manifest aggregator still needs scheduled discovery.
        # Yield to Renovate instead of opening a second update backlog.
        pending = json.loads(
            run(
                "gh",
                "pr",
                "list",
                "--repo",
                repository,
                "--state",
                "open",
                "--json",
                "headRefName",
                "--limit",
                "100",
                capture=True,
            ).stdout
        )
        if any(
            p["headRefName"].startswith(("renovate/", "automated/")) for p in pending
        ):
            print("Another update PR is open; defer the Jellyfin-only refresh.")
            return
    branch = "automated/" + (
        "media-applications" if args.kind == "jellyfin-plugins" else args.kind
    )
    existing = json.loads(
        run(
            "gh",
            "pr",
            "list",
            "--repo",
            repository,
            "--base",
            "main",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number",
            capture=True,
        ).stdout
    )
    if existing:
        print("An update PR is already open; review it before generating another.")
        return
    if (
        run(
            "git",
            "ls-remote",
            "--exit-code",
            "--heads",
            "origin",
            branch,
            capture=True,
            check=False,
        ).returncode
        == 0
    ):
        raise RuntimeError(
            "Closed update branch still exists; delete it after review before rerunning"
        )
    run("git", "config", "user.name", "github-actions[bot]")
    run(
        "git",
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    )
    run("git", "fetch", "origin", "main")
    run("git", "checkout", "-b", branch, "origin/main")
    if args.kind == "upstream":
        if not sync_upstream():
            print("Upstream dependency is already current.")
            return
        run("git", "add", "--", "flake.lock")
        run("git", "commit", "-m", "Update NixFlix dependency")
    else:
        command, patterns = UPDATERS[args.kind]
        run("nix", "develop", "--command", *command)
        changed = formatted_changes(patterns)
        if not changed:
            print("Already current; no PR needed.")
            return
        run("git", "add", "--", *changed)
        run("git", "commit", "-m", "Update " + args.kind)
    run("git", "push", "origin", "HEAD:refs/heads/" + branch)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md") as body:
        body.write(
            f"Update {args.kind} against current main.\n\nCI must pass and the owner must review and merge. Comin deploys merged main.\n"
        )
        if args.kind == "upstream":
            body.write(
                "\nReview the NixFlix lock change and adapter patches, then compare host configuration and recovery checks.\n"
            )
        body.flush()
        run(
            "gh",
            "pr",
            "create",
            "--repo",
            repository,
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            "Update " + args.kind,
            "--body-file",
            body.name,
        )
    # GITHUB_TOKEN PR runs wait for approval; dispatch the generated update explicitly.
    run("gh", "workflow", "run", "ci.yml", "--repo", repository, "--ref", branch)


if __name__ == "__main__":
    main()
