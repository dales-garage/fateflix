import copy
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

import yaml

ROOT = Path(__file__).resolve().parents[2]
with patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
    import ci_reuse as reuse


def archive(evidence):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as bundle:
        bundle.writestr("ci-build-evidence.json", json.dumps(evidence))
    return result.getvalue()


class GraphTests(unittest.TestCase):
    def test_recipes_are_scoped_to_jobs_and_include_the_shared_runner_environment(self):
        before = yaml.safe_load((ROOT / reuse.WORKFLOW).read_text())
        after = copy.deepcopy(before)
        for tool in ("renovate", "gitops"):
            after["jobs"][tool]["steps"].append({"run": "validate updated tool"})
        self.assertEqual(reuse.recipe(before, "checks"), reuse.recipe(after, "checks"))
        self.assertEqual(
            reuse.recipe(before, "production"), reuse.recipe(after, "production")
        )
        after["jobs"]["checks"]["steps"][2][
            "uses"
        ] = "DeterminateSystems/determinate-nix-action@next"
        self.assertNotEqual(
            reuse.recipe(before, "checks"), reuse.recipe(after, "checks")
        )
        self.assertEqual(
            reuse.recipe(before, "production"), reuse.recipe(after, "production")
        )
        after["env"]["NIX_CONFIG"] = "max-jobs = 2"
        self.assertNotEqual(
            reuse.recipe(before, "production"), reuse.recipe(after, "production")
        )

    def test_only_matching_derivations_and_host_pair_reuse(self):
        roots = ["changed-vm", "environment-sensitive", "formatting", "unchanged-vm"]
        options = {n: {"network": n == "environment-sensitive"} for n in roots}
        current = {
            "checks": {n: "old" if n != "changed-vm" else "new" for n in roots},
            "production": "same host closures and canary",
        }
        previous = {
            "run": 42,
            "checks": {n: "old" for n in roots},
            "production": "same host closures and canary",
        }
        result = reuse.select_builds(roots, True, current, previous, options)
        self.assertEqual(result["reused"], ["formatting", "unchanged-vm"])
        self.assertEqual(result["fresh"], ["changed-vm", "environment-sensitive"])
        self.assertFalse(result["production"])
        self.assertTrue(result["reused_production"])
        self.assertEqual(result["source_run"], 42)
        current["production"] = "changed canary"
        self.assertTrue(
            reuse.select_builds(roots, True, current, previous, options)["production"]
        )
        empty = {"checks": {}, "production": None}
        self.assertEqual(
            reuse.select_builds(roots, True, empty, previous, options)["fresh"], roots
        )

    def test_nix_derivation_changes_propagate_to_the_corresponding_identity(self):
        options = {"formatting": {"vm": False, "network": False}}
        drv = "/nix/store/" + "a" * 32 + "-formatting.drv"
        changed = "/nix/store/" + "b" * 32 + "-formatting.drv"
        values = [json.dumps({"formatting": v}) for v in (drv, changed)]
        with patch.object(reuse, "nix", side_effect=values) as evaluate:
            old = reuse.build_ids(["formatting"], options, False)
            new = reuse.build_ids(["formatting"], options, False)
        self.assertNotEqual(old["checks"]["formatting"], new["checks"]["formatting"])
        self.assertIn("drvPath", evaluate.call_args.args[-1])


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.root)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "user.email", "ci@example.test")
        self.workflow = Path(reuse.WORKFLOW)
        self.workflow.parent.mkdir(parents=True)
        self.workflow.write_text("original trusted workflow\n")
        self.old_base = self.commit("trusted base")
        self.git("switch", "-q", "-c", "topic")
        Path("flake.nix").write_text("a")
        self.previous = self.commit("topic change")
        self.git("switch", "-q", "main")
        self.workflow.write_text("reviewed CI tooling update\n")
        self.base = self.commit("updated trusted base")
        self.git("switch", "-q", "topic")
        self.git("merge", "-q", "--no-edit", "main")
        self.head = self.git("rev-parse", "HEAD")
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
        self.event = self.root / "event.json"
        self.metadata = {
            "action": "synchronize",
            "before": self.previous,
            "repository": {"id": 1, "default_branch": "main", "full_name": "org/repo"},
            "pull_request": {
                "number": 91,
                "head": {"sha": self.head, "repo": {"id": 1}},
                "base": {"sha": self.base, "ref": "main", "repo": {"id": 1}},
            },
        }
        self.event.write_text(json.dumps(self.metadata))
        env = patch.dict(
            os.environ,
            {
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_EVENT_PATH": str(self.event),
                "GITHUB_REPOSITORY": "org/repo",
                "GITHUB_SHA": checkout,
                "GITHUB_RUN_ID": "43",
                "GITHUB_RUN_ATTEMPT": "1",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.proof = {
            "schema": 2,
            "repo": "org/repo",
            "pr": 91,
            "head": self.previous,
            "base": self.old_base,
            "run": 42,
            "attempt": 2,
            "checks": {"formatting": "proof"},
            "production": "hosts",
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
        self.git("add", ".")
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
            return archive(self.proof)
        self.fail(path)

    def test_accepts_prior_success_when_workflow_changed_on_trusted_base(self):
        with patch.object(reuse, "api", side_effect=self.api):
            self.assertEqual(reuse.previous_builds(), self.proof)

    def test_rejects_forks_and_policy_changes_in_the_pr(self):
        with patch.object(reuse, "api", side_effect=AssertionError("unexpected API")):
            with patch.object(reuse, "policy_matches", return_value=False):
                self.assertIsNone(reuse.previous_builds())
            self.metadata["pull_request"]["head"]["repo"]["id"] = 2
            self.event.write_text(json.dumps(self.metadata))
            self.assertIsNone(reuse.previous_builds())

    def test_rejects_wrong_run_attempt_previous_head_or_base(self):
        for field, value in (
            ("attempt", 1),
            ("head", self.base),
            ("base", self.previous),
        ):
            with self.subTest(field=field):
                original = self.proof[field]
                self.proof[field] = value
                with patch.object(reuse, "api", side_effect=self.api):
                    self.assertIsNone(reuse.previous_builds())
                self.proof[field] = original

    def test_github_failure_falls_back(self):
        with patch.object(reuse, "api", side_effect=OSError("offline")):
            self.assertIsNone(reuse.previous_builds())

    def test_required_job_records_only_fresh_jobs_from_a_shallow_checkout(self):
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
        builds = {
            "fresh": ["formatting"],
            "reused": ["some-vm"],
            "production": False,
            "identities": {
                "checks": {"formatting": "fresh", "some-vm": "reused"},
                "production": "old",
            },
        }
        proof = clone / "proof.json"
        reuse.write_evidence(builds, proof)
        evidence = json.loads(proof.read_text())
        self.assertEqual(evidence["head"], self.head)
        self.assertEqual(evidence["base"], self.base)
        self.assertEqual(evidence["checks"], {"formatting": "fresh"})
        self.assertIsNone(evidence["production"])
