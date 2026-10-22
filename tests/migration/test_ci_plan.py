import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
import tempfile
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ci_plan", ROOT / "scripts/ci-plan.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.names = ci.catalog(ROOT)

    def select(self, *paths):
        return ci.select(self.names, list(paths))

    def test_host_change_runs_host_checks_and_production_without_vms(self):
        for path in ["hosts/nixflix/gpu.nix", "scripts/nixflix_remux.py"]:
            with self.subTest(path=path):
                plan = self.select(path)
                self.assertTrue(plan["production"])
                self.assertTrue(self.names["host"] <= set(plan["checks"]))
                self.assertFalse(set(plan["checks"]) & self.names["vm"])

    def test_shared_inputs_cover_all_transitive_dependents(self):
        for path in [
            "flake.nix",
            "flake.lock",
            "modules/arr-common/default.nix",
            "lib/secrets/default.nix",
            "pkgs/notifiarr/default.nix",
        ]:
            with self.subTest(path=path):
                plan = self.select(path)
                self.assertEqual(set(plan["checks"]), self.names["all"])
                self.assertTrue(plan["production"])

    def test_navidrome_generated_plugin_is_scoped(self):
        plan = self.select("modules/navidrome/plugins/gen/plugin.nix")
        self.assertEqual(
            set(plan["checks"]),
            self.names["host"]
            | {"formatting", "docs-build", "unit-tests", "navidrome-basic"},
        )
        self.assertTrue(plan["production"])

    def test_grouped_changes_take_the_union(self):
        plan = self.select(
            "modules/navidrome/plugins/gen/plugin.nix",
            "hosts/nixflix/services.nix",
            "renovate.json",
        )
        self.assertTrue(
            self.names["host"] | {"navidrome-basic", "unit-tests", "docs-build"}
            <= set(plan["checks"])
        )
        self.assertTrue(plan["production"])
        self.assertTrue(plan["renovate"])

    def test_docs_changes_select_docs_and_formatting(self):
        plan = self.select("README.md", "docs/operations.md")
        self.assertEqual(plan["checks"], ["docs-build", "formatting"])
        self.assertFalse(plan["production"])
        self.assertTrue(plan["gitops"])
        self.assertFalse(plan["renovate"])

    def test_python_test_changes_need_no_production_or_vm_build(self):
        plan = self.select("tests/migration/test_ci_plan.py")
        self.assertEqual(plan["checks"], ["formatting"])
        self.assertTrue(plan["gitops"])
        self.assertFalse(plan["production"])

    def test_ci_changes_validate_production_without_app_vm_tests(self):
        for path in [
            "scripts/ci-plan.py",
            ".github/workflows/ci.yml",
            "tests/check-names.nix",
        ]:
            plan = self.select(path)
            self.assertTrue(plan["production"])
            self.assertTrue(plan["renovate"])
            self.assertIn("unit-tests", plan["checks"])
            self.assertFalse(set(plan["checks"]) & self.names["vm"])

    def test_individual_fixture_is_scoped_and_shared_fixture_is_broad(self):
        plan = self.select("tests/vm-tests/navidrome-basic.nix")
        self.assertEqual(plan["checks"], ["formatting", "navidrome-basic"])
        plan = self.select("tests/lib/mk-reverse-proxy-test.nix")
        self.assertTrue(self.names["vm"] <= set(plan["checks"]))
        self.assertFalse(plan["production"])

    def test_unknown_paths_and_test_framework_changes_run_everything(self):
        for path in [
            "new-directory/file",
            "tests/default.nix",
            "tests/vm-tests/default.nix",
            "tests/migration/new-fixture.json",
        ]:
            plan = self.select(path)
            self.assertEqual(set(plan["checks"]), self.names["all"])
            self.assertTrue(plan["production"])

    def test_renovate_validation_is_monotonic_in_grouped_changes(self):
        for paths in [
            ["renovate.json", ".github/FUNDING.yml"],
            [".github/FUNDING.yml", "renovate.json"],
        ]:
            self.assertTrue(self.select(*paths)["renovate"])

    def test_unavailable_base_runs_full_suite_without_nix(self):
        with patch.object(
            ci, "run", side_effect=subprocess.CalledProcessError(1, "git")
        ):
            plan = ci.make_plan("missing")
        self.assertEqual(set(plan["checks"]), self.names["all"])
        self.assertTrue(plan["production"])

    def test_full_or_absent_base_never_executes_any_tool(self):
        with patch.object(
            ci, "run", side_effect=AssertionError("must not execute Nix or Git")
        ):
            for base, full in [(None, False), ("000000", False), ("abc", True)]:
                self.assertEqual(
                    set(ci.make_plan(base, full)["checks"]), self.names["all"]
                )

    def test_planning_only_calls_git_and_detects_both_sides_of_renames(self):
        with patch.object(
            ci, "run", side_effect=["abc", "hosts/nixflix/gpu.nix\0README.md\0"]
        ) as run:
            plan = ci.make_plan("abc")
        self.assertTrue(plan["production"])
        self.assertIn("docs-build", plan["checks"])
        self.assertTrue(all(call.args[0] == "git" for call in run.call_args_list))
        self.assertIn("--no-renames", run.call_args_list[1].args)

    def test_catalog_discovers_new_test_filenames_and_rejects_missing_dirs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                ci.catalog(root)
            (root / "tests/vm-tests").mkdir(parents=True)
            (root / "tests/migration").mkdir(parents=True)
            (root / "tests/vm-tests/new-vm.nix").write_text("{}")
            (root / "tests/migration/new-eval.nix").write_text("{}")
            self.assertEqual(
                ci.catalog(root)["all"],
                {"formatting", "docs-build", "unit-tests", "new-vm", "new-eval"},
            )

    def test_matrix_network_and_kvm_flags_are_computed_without_nix(self):
        result = ci.matrix(ROOT, sorted(self.names["all"]))["include"]
        self.assertEqual(
            set(name for entry in result for name in entry["checks"]), self.names["all"]
        )
        self.assertEqual(sum(not entry["vm"] for entry in result), 1)
        for entry in result:
            self.assertTrue(
                all(
                    (name in self.names["vm"]) == entry["vm"]
                    for name in entry["checks"]
                )
            )
            if entry["vm"]:
                self.assertEqual(len(entry["checks"]), 1)
                text = (
                    ROOT / "tests/vm-tests" / (entry["checks"][0] + ".nix")
                ).read_text()
                self.assertEqual(
                    entry["network"],
                    bool(ci.re.search(r"networking\.useDHCP\s*=\s*true\b", text)),
                )
            else:
                self.assertFalse(entry["network"])

    def test_every_selection_keeps_formatting_and_python_tests(self):
        for path in [
            "README.md",
            "renovate.json",
            "hosts/nixflix/default.nix",
            "tests/migration/test_gitops.py",
            ".github/FUNDING.yml",
        ]:
            plan = self.select(path)
            self.assertIn("formatting", plan["checks"])
            self.assertTrue(plan["gitops"])


class RequiredCheckTests(unittest.TestCase):
    def results(self):
        return {
            "prepare": {
                "result": "success",
                "outputs": {
                    "checks": json.dumps(["navidrome-basic"]),
                    "has_checks": "true",
                    "production": "false",
                    "gitops": "false",
                    "renovate": "false",
                },
            },
            "checks": {"result": "success"},
            "production": {"result": "skipped"},
            "gitops": {"result": "skipped"},
            "renovate": {"result": "skipped"},
        }

    def test_only_planned_skips_are_accepted(self):
        ci.verify(self.results())
        for outcome in ["skipped", "failure", "cancelled", None]:
            with self.subTest(outcome=outcome):
                result = self.results()
                result["checks"]["result"] = outcome
                with self.assertRaises(ValueError):
                    ci.verify(result)

    def test_failed_planning_is_never_accepted(self):
        result = self.results()
        result["prepare"]["result"] = "failure"
        with self.assertRaises(ValueError):
            ci.verify(result)

    def test_empty_matrix_can_skip_checks(self):
        result = self.results()
        result["prepare"]["outputs"].update(checks="[]", has_checks="false")
        result["checks"]["result"] = "skipped"
        ci.verify(result)

    def test_inconsistent_or_missing_plan_is_rejected(self):
        result = self.results()
        result["prepare"]["outputs"]["has_checks"] = "false"
        with self.assertRaises(ValueError):
            ci.verify(result)

    def test_each_selected_job_must_succeed(self):
        for job in ("checks", "production", "gitops", "renovate"):
            for outcome in ("skipped", "failure", "cancelled", None):
                with self.subTest(job=job, outcome=outcome):
                    result = self.results()
                    flag = "has_checks" if job == "checks" else job
                    result["prepare"]["outputs"][flag] = "true"
                    result[job]["result"] = outcome
                    with self.assertRaises(ValueError):
                        ci.verify(result)

    def test_missing_job_selection_is_rejected(self):
        result = self.results()
        del result["prepare"]["outputs"]["production"]
        with self.assertRaises(ValueError):
            ci.verify(result)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        self.jobs = self.workflow["jobs"]

    def test_prepare_installs_no_nix_and_executes_no_evaluation(self):
        steps = self.jobs["prepare"]["steps"]
        self.assertFalse(any("nix" in step.get("uses", "").lower() for step in steps))
        self.assertFalse(any("nix eval" in step.get("run", "") for step in steps))
        self.assertEqual(self.jobs["prepare"]["timeout-minutes"], 3)

    def test_required_gate_covers_every_job(self):
        self.assertEqual(
            set(self.jobs["required"]["needs"]), set(self.jobs) - {"required"}
        )
        self.assertEqual(self.jobs["required"]["if"], "always()")
        self.assertTrue(all("timeout-minutes" in job for job in self.jobs.values()))
        self.assertFalse(
            any(job.get("continue-on-error") for job in self.jobs.values())
        )

    def test_renovate_is_separate_from_python_tests(self):
        self.assertFalse(
            any(
                "setup-node" in step.get("uses", "")
                for step in self.jobs["gitops"]["steps"]
            )
        )
        self.assertIn("renovate", self.jobs["renovate"]["if"])

    def test_nix_check_runs_once_and_matrix_is_bounded(self):
        self.assertEqual(self.jobs["checks"]["strategy"]["max-parallel"], 4)
        scripts = "\n".join(s.get("run", "") for s in self.jobs["checks"]["steps"])
        self.assertNotIn("nix eval", scripts)
        self.assertEqual(scripts.count("nix build"), 1)

    def test_all_workflows_keep_bounded_jobs_and_no_cachix_or_devenv(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            workflow = yaml.safe_load(path.read_text())
            for name, job in workflow["jobs"].items():
                with self.subTest(workflow=path.name, job=name):
                    self.assertIn("timeout-minutes", job)
                    for step in job.get("steps", []):
                        self.assertNotIn("cachix", step.get("uses", "").lower())
                        self.assertNotIn("devenv", step.get("uses", "").lower())


if __name__ == "__main__":
    unittest.main()
