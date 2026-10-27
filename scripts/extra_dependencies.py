#!/usr/bin/env python3
"""Audit dependency ownership; refresh supplemental pins in an isolated checkout."""

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

POLICY = "scripts/dependency-coverage.json"
CATALOG = "integrations/nixflix/plugins/jellyfin/plugins.json"
OUTPUTS = ["capabilities/monitoring/notifications.nix", CATALOG]
PIN = re.compile(
    r'\b(?P<kind>image|hash|sha256|rev|tag)\s*=\s*"(?P<value>[^"\n]+)"'
    r'|(?P<revision>github:[^"\s]+/[a-f0-9]{40})'
)
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
SRI = re.compile(r"sha256-[A-Za-z0-9+/]{43}=")


def run(*args, cwd=None, capture=False):
    env = os.environ.copy()
    # Providers and GitHub write credentials are unnecessary for public discovery.
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        env.pop(key, None)
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        env=env,
        stdout=subprocess.PIPE if capture else None,
        text=True,
        timeout=2700,
    ).stdout


def tracked(root):
    return run("git", "ls-files", "-z", cwd=root, capture=True).split("\0")[:-1]


def renovate_dependencies(root):
    config = json.loads((root / "renovate.json").read_text())
    result = set()
    for manager in config["customManagers"]:
        for path in ("hosts/nixflix/containers.json", ".github/package-versions.json"):
            if not any(
                re.search(pattern.strip("/"), path)
                for pattern in manager["managerFilePatterns"]
            ):
                continue
            for pattern in manager["matchStrings"]:
                pattern = re.sub(r"\(\?<([A-Za-z][A-Za-z0-9_]*)>", r"(?P<\1>", pattern)
                for match in re.finditer(pattern, (root / path).read_text()):
                    result.add(match["depName"])
    return result


def audit(root):
    root = Path(root)
    policy = json.loads((root / POLICY).read_text())
    discovered = renovate_dependencies(root)
    entries, unknown = [], []
    for name in tracked(root):
        if not name.endswith(".nix"):
            continue
        for pin in PIN.finditer((root / name).read_text()):
            rules = [
                rule
                for rule in policy["nixPins"]
                if any(fnmatch.fnmatchcase(name, p) for p in rule["paths"])
            ]
            entry = {
                "path": name,
                "pin": pin["value"] or pin["revision"],
                "owner": rules[0]["owner"] if len(rules) == 1 else "unclassified",
            }
            entries.append(entry)
            if entry["owner"] == "unclassified":
                unknown.append(entry)
    containers = json.loads((root / "hosts/nixflix/containers.json").read_text())
    for name, pin in containers.items():
        owner = policy["containers"].get(name, "unclassified")
        if owner == "renovate" and pin.split("@")[0] not in discovered:
            owner = "unclassified"
        entry = {
            "path": "hosts/nixflix/containers.json",
            "name": name,
            "pin": pin,
            "owner": owner,
        }
        entries.append(entry)
        if owner == "unclassified":
            unknown.append(entry)
    lock = json.loads((root / "flake.lock").read_text())
    for name, node in lock["nodes"].items():
        if "locked" in node:
            entries.append(
                {
                    "path": "flake.lock",
                    "name": name,
                    "pin": node["locked"].get("rev", node["locked"].get("narHash")),
                    "owner": (
                        "manual-policy"
                        if name in policy["manualInputs"]
                        else "renovate-lock"
                    ),
                }
            )
    for name, version in json.loads(
        (root / ".github/package-versions.json").read_text()
    ).items():
        entry = {
            "path": ".github/package-versions.json",
            "name": name,
            "pin": version,
            "owner": "renovate" if name in discovered else "unclassified",
        }
        entries.append(entry)
        if entry["owner"] == "unclassified":
            unknown.append(entry)
    entries.extend(
        [
            {
                "path": CATALOG,
                "owner": "supplemental",
                "reason": "ABI-aware discovery; existing verified entries retained if sources disappear.",
            },
            {
                "path": ".github/workflows/*.yml",
                "owner": "renovate",
                "reason": "GitHub Actions and supported runtime declarations.",
            },
            {
                "path": "integrations/nixflix/vendor/provenance.json",
                "owner": "manual-vendor",
                "reason": "Source provenance, not an independently updatable application.",
            },
            {
                "path": "capabilities/, docs/default.nix, modules/flake/outputs.nix",
                "owner": "renovate-lock",
                "reason": "Native services, kernel patches, Python/Node dependencies and documentation tools follow the three locked nixpkgs package sets.",
            },
            {
                "path": ".github/workflows/ci.yml: PyYAML and Renovate validator",
                "owner": "unversioned-tooling",
                "reason": "Fetched on each CI run without a version pin; no repository version to refresh.",
            },
        ]
    )
    return {"dependencies": entries, "unclassified": unknown, "policy": policy}


def image_match(text, repository):
    pattern = re.compile(
        r'(\bimage\s*=\s*")(' + re.escape(repository) + r'@sha256:[a-f0-9]{64})("\s*;)'
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError("Expected exactly one pinned image for " + repository)
    return pattern, matches[0]


def refresh_images(root, policy):
    for image in policy["supplementalImages"]:
        path = root / image["path"]
        before = path.read_text()
        pattern, _ = image_match(before, image["repository"])
        # Discovery uses fully qualified public registries. Keep newer Skopeo
        # independent of the deployed host's older registries.conf format.
        with tempfile.TemporaryDirectory(prefix="fateflix-registry-") as directory:
            registries = Path(directory) / "registries.conf"
            registries.write_text("unqualified-search-registries = []\n")
            metadata = json.loads(
                run(
                    "env",
                    "CONTAINERS_REGISTRIES_CONF=" + str(registries),
                    "skopeo",
                    "--override-os",
                    "linux",
                    "--override-arch",
                    "amd64",
                    "--command-timeout",
                    "90s",
                    "inspect",
                    "--retry-times",
                    "3",
                    "--no-tags",
                    "docker://" + image["repository"] + ":" + image["tag"],
                    cwd=root,
                    capture=True,
                )
            )
        if (
            not DIGEST.fullmatch(metadata.get("Digest", ""))
            or metadata.get("Os") != "linux"
            or metadata.get("Architecture") != "amd64"
        ):
            raise ValueError("Registry did not return a valid Linux amd64 image")
        reference = image["repository"] + "@" + metadata["Digest"]
        path.write_text(pattern.sub(lambda m: m[1] + reference + m[3], before))


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError("Empty or invalid Jellyfin catalog")
    for name, plugin in catalog.items():
        if (
            not isinstance(plugin, dict)
            or not plugin.get("guid")
            or not plugin.get("versions")
        ):
            raise ValueError("Invalid catalog entry: " + name)
        for version in plugin["versions"]:
            if (
                not SRI.fullmatch(version.get("hash", ""))
                or not re.fullmatch(r"\d+(?:\.\d+)+", version.get("version", ""))
                or not version.get("sourceUrl", "").startswith("https://")
                or not version.get("targetAbi")
            ):
                raise ValueError("Unverified catalog version: " + name)


def merge_catalog(previous, current):
    validate_catalog(previous)
    validate_catalog(current)
    result = dict(previous)
    for name, plugin in current.items():
        old = previous.get(name)
        if old and old["guid"] != plugin["guid"]:
            raise ValueError("Plugin identity changed; manual review required: " + name)
        # Keep verified old entries when a repository is temporarily unreachable.
        # Automatic discovery never interprets disappearance as a deletion request.
        versions = {}
        for version in (old or {}).get("versions", []) + plugin["versions"]:
            key = tuple(version.get(k) for k in ("version", "targetAbi", "sourceUrl"))
            if key in versions and versions[key]["hash"] != version["hash"]:
                raise ValueError("Published plugin bytes changed: " + name)
            versions[key] = version
        result[name] = {
            **plugin,
            "versions": sorted(
                versions.values(),
                key=lambda v: tuple(map(int, v["version"].split("."))),
                reverse=True,
            ),
        }
    return result


def refresh_checkout(root, policy):
    previous = json.loads((root / CATALOG).read_text())
    refresh_images(root, policy)
    run(
        "bash",
        "integrations/nixflix/plugins/jellyfin/update.sh",
        "--manifest-only",
        cwd=root,
    )
    current = json.loads((root / CATALOG).read_text())
    (root / CATALOG).write_text(
        json.dumps(
            merge_catalog(previous, current),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
    run("python3", "scripts/renovate-artifacts.py", "check", cwd=root)


def validate_image_edits(root, scratch, policy):
    for image in policy["supplementalImages"]:
        before = (root / image["path"]).read_text()
        after = (scratch / image["path"]).read_text()
        pattern, _ = image_match(before, image["repository"])
        image_match(after, image["repository"])
        normalize = lambda text: pattern.sub(lambda m: m[1] + "IMAGE" + m[3], text)
        if normalize(before) != normalize(after):
            raise ValueError(
                "Image updater changed configuration outside the image pin"
            )


def publish_files(root, scratch, originals, changed):
    if any(
        (root / name).read_bytes() != contents for name, contents in originals.items()
    ):
        raise ValueError("Checkout changed during discovery; refusing stale output")
    staged = {}
    try:
        for name in changed:
            path = root / name
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                stream.write((scratch / name).read_bytes())
                os.fchmod(stream.fileno(), path.stat().st_mode & 0o777)
                staged[name] = Path(stream.name)
        published = []
        try:
            for name, temporary in staged.items():
                os.replace(temporary, root / name)
                published.append(name)
        except OSError:
            for name in published:
                (root / name).write_bytes(originals[name])
            raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)


def refresh(root, dry_run=False):
    root = Path(root)
    report = audit(root)
    if report["unclassified"]:
        raise ValueError("Unclassified dependency pins; run the audit first")
    if run("git", "status", "--porcelain", cwd=root, capture=True).strip():
        raise ValueError(
            "Refresh requires a clean checkout; commit or stash changes first"
        )
    originals = {name: (root / name).read_bytes() for name in OUTPUTS}
    revision = run("git", "rev-parse", "HEAD", cwd=root, capture=True).strip()
    with tempfile.TemporaryDirectory(prefix="fateflix-dependencies-") as directory:
        scratch = Path(directory) / "checkout"
        run("git", "worktree", "add", "--detach", str(scratch), revision, cwd=root)
        try:
            refresh_checkout(scratch, report["policy"])
            changed = run(
                "git", "diff", "--name-only", cwd=scratch, capture=True
            ).splitlines()
            changed = sorted(
                set(changed)
                | set(
                    run(
                        "git",
                        "ls-files",
                        "--others",
                        "--exclude-standard",
                        cwd=scratch,
                        capture=True,
                    ).splitlines()
                )
            )
            if not set(changed) <= set(OUTPUTS):
                raise ValueError(
                    "Discovery changed files outside the supplemental allowlist"
                )
            validate_image_edits(root, scratch, report["policy"])
            if (
                run("git", "status", "--porcelain", cwd=root, capture=True).strip()
                or run("git", "rev-parse", "HEAD", cwd=root, capture=True).strip()
                != revision
            ):
                raise ValueError(
                    "Checkout changed during discovery; refusing stale output"
                )
            if not dry_run:
                publish_files(root, scratch, originals, changed)
        finally:
            run("git", "worktree", "remove", "--force", str(scratch), cwd=root)
    return {"changed": changed, "dry_run": dry_run}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=["audit", "refresh"], nargs="?", default="audit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover updates without changing the checkout",
    )
    args = parser.parse_args()
    root = Path(run("git", "rev-parse", "--show-toplevel", capture=True).strip())
    if args.mode == "audit":
        result = audit(root)
        print(json.dumps(result, indent=2))
        if result["unclassified"]:
            raise SystemExit(1)
    else:
        print(json.dumps(refresh(root, args.dry_run), indent=2))


if __name__ == "__main__":
    main()
