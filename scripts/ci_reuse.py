"""Reuse a successful build only across an otherwise identical Renovate base merge."""

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
VALIDATOR = re.compile(
    rb"^(      - run: npx --yes --package renovate@)"
    rb"([0-9]+\.[0-9]+\.[0-9]+)( renovate-config-validator --strict renovate\.json)$",
    re.M,
)


def git(*args):
    return subprocess.check_output(["git", *args], timeout=15)


def normalize(workflow):
    matches = list(VALIDATOR.finditer(workflow))
    if len(matches) != 1:
        raise ValueError("Expected one Renovate validator command")
    match = matches[0]
    return match[2], VALIDATOR.sub(rb"\g<1><version>\g<3>", workflow)


def fingerprint(commit):
    """Digest all tracked paths, modes and objects, masking just the validator pin."""
    entries = git("ls-tree", "-rz", "--full-tree", commit).split(b"\0")
    for i, entry in enumerate(entries):
        if entry.split(b"\t", 1)[-1] == WORKFLOW.encode():
            mode, kind, _ = entry.split(b"\t", 1)[0].split()
            if mode != b"100644" or kind != b"blob":
                raise ValueError("Unexpected CI workflow mode")
            _, normalized = normalize(git("show", f"{commit}:{WORKFLOW}"))
            entries[i] = (
                mode
                + b" "
                + kind
                + b" "
                + hashlib.sha256(normalized).hexdigest().encode()
                + b"\t"
                + WORKFLOW.encode()
            )
            break
    else:
        raise ValueError("Missing CI workflow")
    return hashlib.sha256(b"\0".join(entries)).hexdigest()


def previous_head(head, base, before=None):
    """Accept a two-parent branch update merging the current default branch."""
    if not (SHA.fullmatch(head) and SHA.fullmatch(base)):
        return None
    parents = git("rev-list", "--parents", "-n", "1", head).decode().split()
    if len(parents) != 3 or parents[2] != base or (before and parents[1] != before):
        return None
    previous = parents[1]
    changed = git("diff", "--no-renames", "--name-only", "-z", previous, head)
    if changed != WORKFLOW.encode() + b"\0":
        return None
    old_version, old = normalize(git("show", f"{previous}:{WORKFLOW}"))
    new_version, new = normalize(git("show", f"{head}:{WORKFLOW}"))
    if old != new or old_version == new_version:
        return None
    old_parts = tuple(map(int, old_version.split(b".")))
    new_parts = tuple(map(int, new_version.split(b".")))
    if old_parts[0] != new_parts[0] or new_parts <= old_parts:
        return None
    return previous


def pr_context(event):
    repo, pr = event["repository"], event["pull_request"]
    if (
        pr["head"]["repo"]["id"] != repo["id"]
        or pr["base"]["repo"]["id"] != repo["id"]
        or pr["base"]["ref"] != repo["default_branch"]
    ):
        return None
    return repo, pr


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


def checkout_matches_event(pr):
    checkout = os.environ["GITHUB_SHA"]
    if not SHA.fullmatch(checkout):
        return False
    if git("rev-parse", "HEAD").decode().strip() != checkout:
        return False
    # The gate uses a shallow checkout. Read the commit header so missing
    # parent objects do not hide the recorded parent IDs.
    headers = git("cat-file", "-p", checkout).split(b"\n\n", 1)[0]
    parents = [
        line[7:].decode()
        for line in headers.splitlines()
        if line.startswith(b"parent ")
    ]
    return parents == [pr["base"]["sha"], pr["head"]["sha"]]


def find_reusable_run(plan):
    """Return a workflow run ID, or zero when fresh checks are needed."""
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return 0
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        ctx = pr_context(event)
        if event.get("action") != "synchronize" or not ctx:
            return 0
        repo, pr = ctx
        if not checkout_matches_event(pr):
            return 0
        previous = previous_head(
            pr["head"]["sha"], pr["base"]["sha"], event.get("before")
        )
        if not previous:
            return 0
        digest = fingerprint("HEAD")
        name = os.environ["GITHUB_REPOSITORY"]
        if name != repo["full_name"]:
            return 0
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
            expected = {
                "schema": 1,
                "repo": name,
                "pr": pr["number"],
                "head": previous,
                "run": run_id,
                "attempt": attempt,
                "fingerprint": digest,
                "checks": plan["checks"],
                "production": True,
            }
            if read_evidence(name, run_id, attempt) == expected:
                return run_id
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ):
        # Missing or malformed evidence never changes the normal test plan.
        print(
            "CI build evidence could not be verified. Running fresh checks.", flush=True
        )
    return 0


def write_evidence(outputs, path):
    """Publish fresh full-build evidence after the gate has accepted the results."""
    if (
        os.environ.get("GITHUB_EVENT_NAME") != "pull_request"
        or outputs["reused_run"] != "0"
        or outputs["production"] != "true"
    ):
        return
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    ctx = pr_context(event)
    if not ctx:
        return
    repo, pr = ctx
    if not checkout_matches_event(pr):
        return
    evidence = {
        "schema": 1,
        "repo": repo["full_name"],
        "pr": pr["number"],
        "head": pr["head"]["sha"],
        "run": int(os.environ["GITHUB_RUN_ID"]),
        "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "fingerprint": fingerprint("HEAD"),
        "checks": json.loads(outputs["checks"]),
        "production": True,
    }
    Path(path).write_text(json.dumps(evidence) + "\n")
