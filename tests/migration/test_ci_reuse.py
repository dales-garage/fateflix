import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
with patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
    import ci_reuse as reuse


def api_archive(evidence):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("ci-build-evidence.json", json.dumps(evidence))
    return output.getvalue()


class ReuseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        previous_dir = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_dir)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "user.email", "ci@example.test")
        path = self.root / reuse.WORKFLOW
        path.parent.mkdir(parents=True)
        self.workflow = (
            "      - run: npx --yes --package renovate@44.261.3 "
            "renovate-config-validator --strict renovate.json\n"
        )
        path.write_text(self.workflow)
        self.commit("initial base")
        self.git("switch", "-q", "-c", "topic")
        (self.root / "flake.nix").write_text("fixture")
        self.previous = self.commit("topic change")
        self.git("switch", "-q", "main")
        path.write_text(self.workflow.replace("44.261.3", "44.263.4"))
        self.base = self.commit("upgrade Renovate")
        self.git("switch", "-q", "topic")
        self.git("merge", "-q", "--no-edit", "main")
        self.head = self.git("rev-parse", "HEAD")
        # Match the two-parent test merge that Actions checks out.
        checkout = self.git(
            "commit-tree",
            "HEAD^{tree}",
            "-p",
            self.base,
            "-p",
            self.head,
            "-m",
            "test merge",
        )
        self.git("checkout", "--quiet", "--detach", checkout)
        metadata = {
            "action": "synchronize",
            "before": self.previous,
            "repository": {"id": 1, "default_branch": "main", "full_name": "org/repo"},
            "pull_request": {
                "number": 91,
                "head": {"sha": self.head, "repo": {"id": 1}},
                "base": {"sha": self.base, "ref": "main", "repo": {"id": 1}},
            },
        }
        self.event = self.root / "event.json"
        self.event.write_text(json.dumps(metadata))
        self.env = {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(self.event),
            "GITHUB_REPOSITORY": "org/repo",
            "GITHUB_SHA": checkout,
            "GITHUB_RUN_ID": "43",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        env = patch.dict(os.environ, self.env)
        env.start()
        self.addCleanup(env.stop)
        self.plan = {"checks": ["formatting", "vm-basic"], "production": True}
        self.evidence = {
            "schema": 1,
            "repo": "org/repo",
            "pr": 91,
            "head": self.previous,
            "run": 42,
            "attempt": 2,
            "fingerprint": reuse.fingerprint(self.previous),
            "checks": self.plan["checks"],
            "production": True,
        }
        self.run = {
            "id": 42,
            "run_attempt": 2,
            "path": reuse.WORKFLOW,
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "head_sha": self.previous,
            "head_repository": {"id": 1},
            "pull_requests": [{"number": 91}],
        }

    def git(self, *args):
        return subprocess.check_output(["git", *args], text=True).strip()

    def commit(self, message):
        self.git("add", str(self.root / reuse.WORKFLOW))
        if (self.root / "flake.nix").is_file():
            self.git("add", "flake.nix")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def api(self, path):
        if "/workflows/ci.yml/runs?" in path:
            self.assertIn("head_sha=" + self.previous, path)
            return json.dumps({"workflow_runs": [self.run]}).encode()
        if path.endswith("/runs/42/artifacts"):
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "name": "ci-build-evidence-2",
                            "id": 7,
                            "expired": False,
                            "size_in_bytes": 400,
                        }
                    ]
                }
            ).encode()
        if path.endswith("/artifacts/7/zip"):
            return api_archive(self.evidence)
        self.fail(path)

    def test_base_merge_reuses_exact_tested_tree_with_fresh_validator_pin(self):
        self.assertEqual(
            reuse.previous_head(self.head, self.base, self.previous), self.previous
        )
        self.assertEqual(reuse.fingerprint("HEAD"), reuse.fingerprint(self.previous))
        with patch.object(reuse, "api", side_effect=self.api):
            self.assertEqual(reuse.find_reusable_run(self.plan), 42)

    def test_proof_must_cover_exact_source_and_all_selected_checks(self):
        for change in [
            {"checks": ["formatting"]},
            {"production": False},
            {"fingerprint": "wrong"},
            {"attempt": 1},
            {"pr": 92},
        ]:
            with self.subTest(change=change):
                old = self.evidence.copy()
                self.evidence.update(change)
                with patch.object(reuse, "api", side_effect=self.api):
                    self.assertEqual(reuse.find_reusable_run(self.plan), 0)
                self.evidence = old

    def test_workflow_run_must_be_successful_for_same_pr_and_head(self):
        for change in [
            {"conclusion": "failure"},
            {"head_sha": self.base},
            {"pull_requests": [{"number": 92}]},
            {"head_repository": {"id": 2}},
        ]:
            with self.subTest(change=change):
                old = self.run.copy()
                self.run.update(change)
                with patch.object(reuse, "api", side_effect=self.api):
                    self.assertEqual(reuse.find_reusable_run(self.plan), 0)
                self.run = old

    def test_source_and_nonvalidator_workflow_changes_invalidate_reuse(self):
        updated = self.root / reuse.WORKFLOW
        text = updated.read_text()
        for delta in ["        run: echo another-step\n", "major", "source", "mode"]:
            with self.subTest(delta=delta):
                self.git("checkout", "--quiet", "--detach", self.base)
                if delta == "source":
                    (self.root / "flake.nix").write_text("different")
                elif delta == "mode":
                    updated.chmod(0o755)
                elif delta == "major":
                    updated.write_text(text.replace("44.263.4", "45.0.0"))
                else:
                    updated.write_text(text + delta)
                if delta == "source":
                    self.git("add", "flake.nix")
                base = self.commit("unrelated base change")
                self.git("checkout", "--quiet", "--detach", self.previous)
                merge = self.git(
                    "commit-tree",
                    base + "^{tree}",
                    "-p",
                    self.previous,
                    "-p",
                    base,
                    "-m",
                    "merge",
                )
                self.assertTrue(
                    reuse.previous_head(merge, base, self.previous) is None
                    or reuse.fingerprint(merge) != reuse.fingerprint(self.previous)
                )

    def test_github_failure_falls_back_and_forks_never_request_artifacts(self):
        with patch.object(reuse, "api", side_effect=OSError("offline")):
            self.assertEqual(reuse.find_reusable_run(self.plan), 0)
        event = json.loads(self.event.read_text())
        event["pull_request"]["head"]["repo"]["id"] = 2
        self.event.write_text(json.dumps(event))
        with patch.object(
            reuse, "api", side_effect=AssertionError("unexpected API request")
        ):
            self.assertEqual(reuse.find_reusable_run(self.plan), 0)

    def test_required_job_can_record_evidence_from_a_shallow_checkout(self):
        self.git("branch", "test-merge", "HEAD")
        clone = self.root / "shallow"
        self.git(
            "clone",
            "--quiet",
            "--depth=1",
            "--branch",
            "test-merge",
            self.root.as_uri(),
            str(clone),
        )
        self.addCleanup(os.chdir, self.root)
        os.chdir(clone)
        self.assertEqual(self.git("rev-parse", "--is-shallow-repository"), "true")
        pr = json.loads(self.event.read_text())["pull_request"]
        self.assertTrue(reuse.checkout_matches_event(pr))
        proof = clone / "proof.json"
        reuse.write_evidence(
            {
                "reused_run": "0",
                "production": "true",
                "has_checks": "true",
                "checks": json.dumps(self.plan["checks"]),
            },
            proof,
        )
        self.assertEqual(
            json.loads(proof.read_text())["fingerprint"], reuse.fingerprint("HEAD")
        )

    def test_recorded_evidence_matches_checkout_and_does_not_chain(self):
        path = self.root / "proof.json"
        outputs = {
            "reused_run": "42",
            "production": "true",
            "has_checks": "true",
            "checks": json.dumps(self.plan["checks"]),
        }
        reuse.write_evidence(outputs, path)
        self.assertFalse(path.exists())
        reuse.write_evidence(dict(outputs, reused_run="0"), path)
        evidence = json.loads(path.read_text())
        self.assertEqual(evidence["head"], self.head)
        self.assertEqual(evidence["run"], 43)
        self.assertEqual(evidence["fingerprint"], reuse.fingerprint("HEAD"))
