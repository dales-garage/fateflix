#!/usr/bin/env python3
"""Select changed Nix derivations and enforce the resulting required CI jobs."""

import argparse
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import tempfile


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def nix_json(path, attr, *extra):
    return json.loads(
        run(
            "nix",
            "eval",
            "--no-write-lock-file",
            "--json",
            f".{attr}",
            *extra,
            cwd=path,
        )
    )


def manifest(path):
    return {
        "checks": nix_json(
            path,
            "#checks.x86_64-linux",
            "--apply",
            "checks: builtins.mapAttrs (_: check: check.drvPath) checks",
        ),
        "production": nix_json(
            path,
            "#nixosConfigurations.nixflix-production.config.system.build.toplevel.drvPath",
        ),
    }


def full_plan(checks, reason):
    return {
        "checks": sorted(checks),
        "production": True,
        "gitops": True,
        "reason": reason,
    }


def select(head, base, changed):
    return {
        "checks": sorted(
            name
            for name, drv in head["checks"].items()
            if base["checks"].get(name) != drv
        ),
        "production": head["production"] != base["production"],
        "gitops": any(
            fnmatch.fnmatchcase(path, pattern)
            for path in changed
            for pattern in (
                "scripts/*",
                "tests/migration/*",
                "pkgs/notifiarr/update.py",
                "renovate.json",
                ".github/workflows/*",
            )
        ),
        "reason": "Compare check and production derivations against the base commit",
    }


def make_plan(base_ref=None, full=False):
    head_dir = Path.cwd()
    if full or not base_ref or set(base_ref) == {"0"}:
        names = nix_json(
            head_dir, "#checks.x86_64-linux", "--apply", "builtins.attrNames"
        )
        return full_plan(names, "Full run requested or no comparison base available")

    try:
        base_sha = run("git", "rev-parse", "--verify", f"{base_ref}^{{commit}}")
        changed = run("git", "diff", "--name-only", "-z", base_sha, "HEAD").split("\0")
    except subprocess.CalledProcessError:
        names = nix_json(
            head_dir, "#checks.x86_64-linux", "--apply", "builtins.attrNames"
        )
        return full_plan(names, "Base commit unavailable; full suite required")
    # A head evaluation error must fail CI, never turn into an empty test matrix.
    head = manifest(head_dir)
    try:
        with tempfile.TemporaryDirectory(prefix="nixflix-ci-base-") as directory:
            worktree = str(Path(directory) / "checkout")
            run("git", "worktree", "add", "--detach", worktree, base_sha)
            try:
                base = manifest(worktree)
            finally:
                run("git", "worktree", "remove", "--force", worktree)
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(
            f"Base comparison unavailable ({type(exc).__name__}); running the full suite."
        )
        return full_plan(head["checks"], "Base comparison failed; full suite required")
    return select(head, base, changed)


def verify(results):
    prepare = results.get("prepare", {})
    if prepare.get("result") != "success":
        raise ValueError("CI planning did not succeed")
    outputs = prepare.get("outputs", {})
    checks = json.loads(outputs["checks"])
    if (
        not isinstance(checks, list)
        or outputs.get("has_checks") != str(bool(checks)).lower()
    ):
        raise ValueError("Invalid check selection")
    for job, flag in (
        ("checks", "has_checks"),
        ("production", "production"),
        ("gitops", "gitops"),
    ):
        value = outputs.get(flag)
        if value not in {"true", "false"}:
            raise ValueError(f"Missing or invalid selection for {job}")
        expected = "success" if value == "true" else "skipped"
        actual = results.get(job, {}).get("result")
        if actual != expected:
            raise ValueError(f"{job}: expected {expected}, got {actual}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "verify"])
    parser.add_argument("--base")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    if args.command == "verify":
        verify(json.loads(os.environ["CI_RESULTS"]))
        print("Every selected job passed; only unselected jobs were skipped.")
        return

    plan = make_plan(args.base, args.full)
    outputs = {
        "checks": plan["checks"],
        "has_checks": bool(plan["checks"]),
        "production": plan["production"],
        "gitops": plan["gitops"],
    }
    print(json.dumps(plan, indent=2))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            for key, value in outputs.items():
                stream.write(f"{key}={json.dumps(value, separators=(',', ':'))}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write("## CI selection\n\n" + plan["reason"] + "\n\n")
            stream.write(
                "Checks: " + (", ".join(plan["checks"]) or "none changed") + "\n\n"
            )
            for job in ("production", "gitops"):
                stream.write(f"- {job}: {'run' if plan[job] else 'skip (unchanged)'}\n")


if __name__ == "__main__":
    main()
