"""Compute and reuse CI coverage per Nix derivation and runner recipe."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

WORKFLOW = ".github/workflows/ci.yml"
ARTIFACT = "ci-build-evidence"
MAX_EVIDENCE_BYTES = 16_384
SHA = re.compile(r"[a-f0-9]{40}")
DRV = re.compile(r"/nix/store/[0-9a-z]{32}-[^/\s]+\.drv")
POLICY = [WORKFLOW, ".github/requirements-ci.txt", "scripts/"]
POLICY_CODE = ["scripts/ci-plan.py", "scripts/ci_reuse.py"]
HOST_TARGETS = [
    f".#nixosConfigurations.nixflix-{role}.config.system.build.toplevel.drvPath"
    for role in ("production", "staging")
]


def git(*args):
    return subprocess.check_output(["git", *args], timeout=15)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def nix(*args):
    return subprocess.check_output(
        ["nix", "eval", "--no-write-lock-file", *args], text=True, timeout=180
    ).strip()


def recipe(workflow, job):
    """Exclude job scheduling. Commands, actions, environment and runner still count."""
    scheduler = {"name", "needs", "if", "strategy"}
    runner = {k: v for k, v in workflow["jobs"][job].items() if k not in scheduler}
    return digest([workflow.get("env", {}), workflow.get("permissions", {}), runner])


def build_ids(roots, options, hosts):
    import yaml

    workflow = yaml.safe_load(Path(WORKFLOW).read_text())
    check_recipe = recipe(workflow, "checks")
    checks = {}
    # Evict the evaluator between groups so the full suite fits on hosted runners.
    for start in range(0, len(roots), 6):
        names = roots[start : start + 6]
        names_expr = "[ " + " ".join(map(json.dumps, names)) + " ]"
        selected = (
            "checks: builtins.listToAttrs (map (name: { inherit name; "
            "value = checks.${name}.drvPath; }) " + names_expr + ")"
        )
        paths = json.loads(nix("--json", ".#checks.x86_64-linux", "--apply", selected))
        if set(paths) != set(names) or not all(
            DRV.fullmatch(v) for v in paths.values()
        ):
            raise ValueError("Nix did not return the requested check derivations")
        for name, path in paths.items():
            checks[name] = digest([path, check_recipe, options[name]])
    host_id = None
    if hosts:
        paths = [nix("--raw", target) for target in HOST_TARGETS]
        if not all(DRV.fullmatch(p) for p in paths):
            raise ValueError("Nix did not return both host derivations")
        canary = git(
            "ls-tree",
            "-rz",
            "HEAD",
            "--",
            "scripts/check-secret-canary.py",
            "capabilities/secrets",
        )
        host_id = digest(
            [paths, recipe(workflow, "production"), hashlib.sha256(canary).hexdigest()]
        )
    return {"checks": checks, "production": host_id}


def pr_context():
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return None
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    repo, pr = event["repository"], event["pull_request"]
    if (
        not pr["head"].get("repo")
        or pr["head"]["repo"]["id"] != repo["id"]
        or pr["base"]["repo"]["id"] != repo["id"]
        or pr["base"]["ref"] != repo["default_branch"]
        or repo["full_name"] != os.environ["GITHUB_REPOSITORY"]
    ):
        return None
    checkout = os.environ["GITHUB_SHA"]
    if (
        not SHA.fullmatch(checkout)
        or git("rev-parse", "HEAD").decode().strip() != checkout
    ):
        return None
    # The required job uses a shallow checkout. The commit header still has
    # both parent IDs even when the parent objects were not downloaded.
    headers = git("cat-file", "-p", checkout).split(b"\n\n", 1)[0]
    parents = [
        line[7:].decode()
        for line in headers.splitlines()
        if line.startswith(b"parent ")
    ]
    if parents != [pr["base"]["sha"], pr["head"]["sha"]] or not all(
        SHA.fullmatch(p) for p in parents
    ):
        return None
    return event, repo, pr


def policy_matches(base, head, paths=POLICY):
    return (
        git("diff", "--no-renames", "--name-only", "-z", base, head, "--", *paths)
        == b""
    )


def api(path):
    return subprocess.check_output(
        ["gh", "api", "--method", "GET", path], timeout=15, stderr=subprocess.PIPE
    )


def read_evidence(repo, run_id, attempt):
    artifacts = json.loads(api(f"repos/{repo}/actions/runs/{run_id}/artifacts"))[
        "artifacts"
    ]
    candidates = [
        a
        for a in artifacts
        if a["name"] == f"{ARTIFACT}-{attempt}"
        and not a["expired"]
        and 0 < a["size_in_bytes"] <= MAX_EVIDENCE_BYTES
    ]
    if len(candidates) != 1 or type(candidates[0]["id"]) is not int:
        return None
    data = api(f"repos/{repo}/actions/artifacts/{candidates[0]['id']}/zip")
    if len(data) > MAX_EVIDENCE_BYTES:
        return None
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = archive.infolist()
        if (
            len(files) != 1
            or files[0].filename != "ci-build-evidence.json"
            or files[0].file_size > MAX_EVIDENCE_BYTES
        ):
            return None
        return json.loads(archive.read(files[0]))


def pr_previous(event, pr):
    previous = event.get("before")
    if previous is None:
        parents = (
            git("rev-list", "--parents", "-n", "1", pr["head"]["sha"]).decode().split()
        )
        if len(parents) == 3 and parents[2] == pr["base"]["sha"]:
            previous = parents[1]
    return previous if isinstance(previous, str) and SHA.fullmatch(previous) else None


def previous_builds():
    """Load direct successful builds from a previous trusted same-PR run."""
    try:
        ctx = pr_context()
        if not ctx:
            return None
        event, repo, pr = ctx
        previous = pr_previous(event, pr)
        head, base = pr["head"]["sha"], pr["base"]["sha"]
        if (
            event["action"] != "synchronize"
            or not isinstance(previous, str)
            or not SHA.fullmatch(previous)
            or previous == head
            or not policy_matches(base, head)
            or not policy_matches(base, "HEAD")
            or not policy_matches(previous, head, POLICY_CODE)
        ):
            return None
        name = repo["full_name"]
        runs = json.loads(
            api(
                f"repos/{name}/actions/workflows/ci.yml/runs"
                f"?event=pull_request&status=success&head_sha={previous}&per_page=3"
            )
        )["workflow_runs"]
        for run in runs:
            run_id, attempt = run["id"], run["run_attempt"]
            if (
                type(run_id) is not int
                or type(attempt) is not int
                or run["path"] != WORKFLOW
                or run["event"] != "pull_request"
                or run["status"] != "completed"
                or run["conclusion"] != "success"
                or run["head_sha"] != previous
                or run["head_repository"]["id"] != repo["id"]
                or not any(p["number"] == pr["number"] for p in run["pull_requests"])
            ):
                continue
            proof = read_evidence(name, run_id, attempt)
            if not isinstance(proof, dict):
                continue
            identity = {
                "schema": 2,
                "repo": name,
                "pr": pr["number"],
                "head": previous,
                "run": run_id,
                "attempt": attempt,
            }
            if any(proof.get(k) != v for k, v in identity.items()):
                continue
            old_base = proof.get("base")
            if not isinstance(old_base, str) or not SHA.fullmatch(old_base):
                continue
            ancestral = subprocess.run(
                ["git", "merge-base", "--is-ancestor", old_base, base], timeout=15
            )
            if ancestral.returncode or not policy_matches(old_base, previous):
                continue
            return proof
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ):
        print(
            "Prior CI evidence could not be verified. Running fresh checks.", flush=True
        )
    return None


def select_builds(checks, hosts, identities, previous, options):
    prior_checks = (previous or {}).get("checks")
    if not isinstance(prior_checks, dict):
        prior_checks = {}
    repeated = [
        n
        for n in checks
        if not options[n]["network"]
        and identities["checks"].get(n)
        and identities["checks"][n] == prior_checks.get(n)
    ]
    reuse_hosts = bool(
        hosts
        and identities["production"]
        and identities["production"] == (previous or {}).get("production")
    )
    return {
        "fresh": [n for n in checks if n not in repeated],
        "reused": repeated,
        "production": hosts and not reuse_hosts,
        "reused_production": reuse_hosts,
        "source_run": previous["run"] if repeated or reuse_hosts else 0,
        "identities": identities,
    }


def write_evidence(builds, path):
    ctx = pr_context()
    if not ctx:
        return
    _, repo, pr = ctx
    identities = builds["identities"]
    checks = {
        n: identities["checks"][n] for n in builds["fresh"] if n in identities["checks"]
    }
    production = identities["production"] if builds["production"] else None
    if not checks and not production:
        return
    proof = {
        "schema": 2,
        "repo": repo["full_name"],
        "pr": pr["number"],
        "head": pr["head"]["sha"],
        "base": pr["base"]["sha"],
        "run": int(os.environ["GITHUB_RUN_ID"]),
        "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "checks": checks,
        "production": production,
    }
    Path(path).write_text(json.dumps(proof) + "\n")
