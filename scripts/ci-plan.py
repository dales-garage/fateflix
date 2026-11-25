#!/usr/bin/env python3
"""Plan CI from repository paths without installing Nix or evaluating flakes."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

import ci_reuse


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
        if path.endswith(".nix"):
            production = True
        if (
            path == "flake.nix"
            or path == "flake.lock"
            or path.startswith(("lib/", "pkgs/"))
        ):
            return full_plan(
                names["all"], "Shared Nix inputs or packages changed; full suite"
            )
        if path.startswith("hosts/"):
            checks |= names["host"]
            production = True
            reasons.add("host configuration")
            continue
        if path.startswith(("modules/", "capabilities/", "integrations/")):
            # Generated plugin metadata is application-scoped. Keep host
            # validation even if Navidrome is enabled on production later.
            if path.startswith("integrations/nixflix/plugins/navidrome/gen/"):
                checks |= {"navidrome-basic", "unit-tests", "docs-build"}
                checks |= names["host"]
                production = True
                reasons.add("Navidrome generated plugins")
                continue
            return full_plan(names["all"], "Shared Nix modules changed; full suite")
        if path in {
            "scripts/ci-plan.py",
            "tests/check-names.nix",
            ".github/requirements-ci.txt",
        } or path.startswith(".github/workflows/"):
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
    evaluate = results.get("evaluate", {})
    if prepare.get("result") != "success":
        raise ValueError("CI planning did not succeed")
    if evaluate.get("result") != "success":
        raise ValueError("Full flake evaluation did not succeed")
    outputs = prepare["outputs"]
    checks = json.loads(outputs["checks"])
    if (
        not isinstance(checks, list)
        or sorted(set(checks)) != checks
        or outputs.get("has_checks") != str(bool(checks)).lower()
    ):
        raise ValueError("Invalid check selection")
    for flag in ("production", "gitops", "renovate"):
        if outputs.get(flag) not in {"true", "false"}:
            raise ValueError(f"Missing or invalid selection for {flag}")
    evaluated = evaluate["outputs"]
    builds = json.loads(evaluated["builds"])
    verify_builds(checks, outputs["production"] == "true", evaluated, builds)
    for job, selected in (
        ("checks", bool(builds["fresh"])),
        ("production", builds["production"]),
        ("gitops", outputs["gitops"] == "true"),
        ("renovate", outputs["renovate"] == "true"),
    ):
        expected = "success" if selected else "skipped"
        actual = results.get(job, {}).get("result")
        if actual != expected:
            raise ValueError(f"{job}: expected {expected}, got {actual}")
    return builds


def verify_builds(checks, production, outputs, builds):
    fresh, reused = builds["fresh"], builds["reused"]
    identities = builds["identities"]
    source = builds["source_run"]
    if (
        not isinstance(fresh, list)
        or not isinstance(reused, list)
        or sorted(fresh + reused) != checks
        or type(builds["production"]) is not bool
        or type(builds["reused_production"]) is not bool
        or builds["production"] + builds["reused_production"] != int(production)
        or outputs.get("has_checks") != str(bool(fresh)).lower()
        or outputs.get("production") != str(builds["production"]).lower()
        or json.loads(outputs["matrix"]) != matrix(Path.cwd(), fresh)
        or type(source) is not int
        or source < 0
        or bool(source) != bool(reused or builds["reused_production"])
        or not set(reused) <= set(identities["checks"])
        or (builds["reused_production"] and not identities["production"])
    ):
        raise ValueError("Invalid build coverage")


def graph_plan(planned, full=False):
    checks = json.loads(planned["checks"])
    hosts = planned["production"] == "true"
    options = {
        name: {"vm": entry["vm"], "network": entry["network"]}
        for entry in matrix(Path.cwd(), checks)["include"]
        for name in entry["checks"]
    }
    identities = {"checks": {}, "production": None}
    # Pushes, forks, and other events already get the ordinary fresh plan.
    try:
        if ci_reuse.pr_context():
            identities = ci_reuse.build_ids(checks, options, hosts)
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        ImportError,
        subprocess.SubprocessError,
    ):
        print("Nix graph evidence unavailable. Running all selected jobs fresh.")
    previous = (
        ci_reuse.previous_builds()
        if not full and identities != {"checks": {}, "production": None}
        else None
    )
    builds = ci_reuse.select_builds(checks, hosts, identities, previous, options)
    outputs = {
        "has_checks": bool(builds["fresh"]),
        "production": builds["production"],
        "matrix": matrix(Path.cwd(), builds["fresh"]),
        "builds": builds,
    }
    lines = [
        "## Nix build selection",
        "Fresh checks: " + (", ".join(builds["fresh"]) or "none"),
        "Host builds: "
        + (
            "fresh"
            if builds["production"]
            else "reused" if builds["reused_production"] else "outside scope"
        ),
    ]
    if builds["source_run"]:
        source = builds["source_run"]
        url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{source}"
        lines.append(
            f"Reused from [CI run {source}]({url}): "
            + (", ".join(builds["reused"]) or "host builds only")
        )
    print("\n".join(lines), flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write("\n\n".join(lines) + "\n")
    write_outputs(outputs)


def write_outputs(outputs):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            for key, value in outputs.items():
                stream.write(f"{key}={json.dumps(value, separators=(',', ':'))}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "graph", "verify", "record"])
    parser.add_argument("--base")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.command in {"verify", "record"}:
        builds = verify(json.loads(os.environ["CI_RESULTS"]))
        if args.command == "record":
            if args.evidence is None:
                parser.error("record requires --evidence")
            ci_reuse.write_evidence(builds, args.evidence)
        else:
            print(
                "Fresh jobs passed. Each selected Nix target is covered by a fresh or verified earlier build."
            )
        return
    if args.command == "graph":
        graph_plan(json.loads(os.environ["CI_PLAN"]), args.full)
        return

    started = time.monotonic()
    plan = make_plan(args.base, args.full)
    if not plan["renovate"]:
        try:
            ctx = ci_reuse.pr_context()
            if ctx and ctx[0]["action"] == "synchronize":
                previous = ci_reuse.pr_previous(ctx[0], ctx[2])
                if previous and not ci_reuse.policy_matches(
                    previous, "HEAD", [ci_reuse.WORKFLOW]
                ):
                    plan["renovate"] = True
        except (KeyError, OSError, ValueError, subprocess.SubprocessError):
            plan["renovate"] = True
    outputs = {
        "checks": plan["checks"],
        "has_checks": bool(plan["checks"]),
        "production": plan["production"],
        "gitops": plan["gitops"],
        "renovate": plan["renovate"],
    }
    print(
        f"Selected {len(plan['checks'])} candidate checks in {time.monotonic() - started:.3f}s without Nix",
        flush=True,
    )
    print(json.dumps(plan, indent=2))
    write_outputs(outputs)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write("## CI selection\n\n" + plan["reason"] + "\n\n")
            stream.write(
                "Candidates: " + (", ".join(plan["checks"]) or "none changed") + "\n\n"
            )
            for job in ("production", "gitops", "renovate"):
                stream.write(
                    f"- {job}: {'selected' if plan[job] else 'outside scope'}\n"
                )


if __name__ == "__main__":
    main()
