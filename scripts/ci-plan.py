#!/usr/bin/env python3
"""Plan CI from repository paths without installing Nix or evaluating flakes."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time


def run(*args):
    return subprocess.check_output(args, text=True, timeout=60).strip()


def catalog(root):
    """Match tests/check-names.nix; flake evaluation asserts this stays complete."""
    root = Path(root)
    vm = {
        p.stem
        for p in (root / "tests/vm-tests").glob("*.nix")
        if p.is_file() and not p.is_symlink() and p.name != "default.nix"
    }
    host = {
        p.stem
        for p in (root / "tests/migration").glob("*-eval.nix")
        if p.is_file() and not p.is_symlink()
    }
    if not vm or not host:
        raise ValueError("CI check directories are missing or empty")
    if vm & host or not all(
        re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in vm | host
    ):
        raise ValueError("CI check names must be unique safe attribute names")
    return {
        "vm": vm,
        "host": host,
        "all": vm
        | host
        | {"formatting", "check-flake-file", "docs-build", "unit-tests"},
    }


def full_plan(checks, reason):
    return {
        "checks": sorted(checks),
        "production": True,
        "gitops": True,
        "renovate": True,
        "reason": reason,
    }


def select(names, changed):
    checks, production, renovate = {"formatting"}, False, False
    reasons = set()
    for path in changed:
        if not path:
            continue
        if (
            path == "flake.nix"
            or path == "flake.lock"
            or path.startswith(("lib/", "pkgs/"))
        ):
            return full_plan(
                names["all"], "Shared Nix inputs or packages changed; full suite"
            )
        if path.startswith("modules/"):
            # Generated plugin metadata is application-scoped. Keep host
            # validation even if Navidrome is enabled on production later.
            if path.startswith(
                "modules/_support/compat/modules/navidrome/plugins/gen/"
            ):
                checks |= {"navidrome-basic", "unit-tests", "docs-build"}
                checks |= names["host"]
                production = True
                reasons.add("Navidrome generated plugins")
                continue
            return full_plan(names["all"], "Shared Nix modules changed; full suite")
        if path.startswith("hosts/"):
            checks |= names["host"]
            production = True
            reasons.add("production host")
        elif path in {"scripts/ci-plan.py", "tests/check-names.nix"} or path.startswith(
            ".github/workflows/"
        ):
            checks |= names["host"] | {"unit-tests"}
            production = True
            renovate = True
            if path == ".github/workflows/docs.yml":
                checks.add("docs-build")
            reasons.add("CI infrastructure")
        elif path.startswith("scripts/"):
            checks |= names["host"]
            production = True
            reasons.add("host tooling")
        elif path.startswith("tests/migration/"):
            name = Path(path).stem
            if path.endswith("-eval.nix"):
                if name in names["host"]:
                    checks.add(name)
                else:
                    checks.update(names["host"])
            elif not path.endswith(".py"):
                return full_plan(
                    names["all"], "Unknown migration fixture changed; full suite"
                )
            reasons.add("migration tests")
        elif path.startswith("tests/vm-tests/") and Path(path).stem in names["vm"]:
            checks.add(Path(path).stem)
            reasons.add("VM test fixture")
        elif path.startswith("tests/lib/"):
            checks |= names["vm"]
            reasons.add("shared VM fixture")
        elif path.startswith("tests/unit-tests/"):
            checks.add("unit-tests")
            reasons.add("Nix unit tests")
        elif path.startswith("docs/") or path.endswith(".md") or path == "mkdocs.yml":
            checks.add("docs-build")
            reasons.add("documentation")
        elif path in {"treefmt.nix", ".gitignore", ".editorconfig"}:
            reasons.add("formatting")
        elif path == "renovate.json":
            renovate = True
            reasons.add("Renovate configuration")
        elif path in {".github/FUNDING.yml", ".github/dependabot.yml"}:
            renovate |= path.endswith("dependabot.yml")
            reasons.add("GitHub metadata")
        else:
            return full_plan(
                names["all"], "Unclassified path changed; full suite: " + path
            )
    if not checks <= names["all"]:
        raise ValueError("Selected an unknown check")
    return {
        "checks": sorted(checks),
        "production": production,
        "gitops": True,
        "renovate": renovate,
        "reason": "Path selection: "
        + (", ".join(sorted(reasons)) or "no source changes"),
    }


def make_plan(base_ref=None, full=False):
    names = catalog(Path.cwd())
    if full or not base_ref or set(base_ref) == {"0"}:
        return full_plan(
            names["all"], "Full run requested or no comparison base available"
        )

    try:
        base_sha = run("git", "rev-parse", "--verify", f"{base_ref}^{{commit}}")
        changed = run(
            "git", "diff", "--no-renames", "--name-only", "-z", base_sha, "HEAD"
        ).split("\0")
    except subprocess.CalledProcessError:
        return full_plan(names["all"], "Base commit unavailable; full suite required")
    return select(names, changed)


def matrix(root, checks):
    names = catalog(root)
    regular = [name for name in checks if name not in names["vm"]]
    result = (
        [{"name": "Nix checks", "checks": regular, "vm": False, "network": False}]
        if regular
        else []
    )
    for name in checks:
        if name not in names["vm"]:
            continue
        source = (Path(root) / "tests/vm-tests" / (name + ".nix")).read_text()
        result.append(
            {
                "name": name,
                "checks": [name],
                "vm": True,
                "network": bool(re.search(r"networking\.useDHCP\s*=\s*true\b", source)),
            }
        )
    return {"include": result}


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
        ("renovate", "renovate"),
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

    started = time.monotonic()
    plan = make_plan(args.base, args.full)
    outputs = {
        "checks": plan["checks"],
        "has_checks": bool(plan["checks"]),
        "production": plan["production"],
        "gitops": plan["gitops"],
        "renovate": plan["renovate"],
        "matrix": matrix(Path.cwd(), plan["checks"]),
    }
    print(
        f"Selected {len(plan['checks'])} checks in {time.monotonic() - started:.3f}s without Nix",
        flush=True,
    )
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
            for job in ("production", "gitops", "renovate"):
                stream.write(
                    f"- {job}: {'run' if plan[job] else 'skip (outside scope)'}\n"
                )


if __name__ == "__main__":
    main()
