import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ci_plan", ROOT / "scripts/ci-plan.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "checks": {"navidrome-basic": "nav-old.drv", "radarr-basic": "radarr.drv"},
            "production": "production.drv",
        }

    def test_navidrome_update_does_not_select_radarr_or_unchanged_production(self):
        head = copy.deepcopy(self.base)
        head["checks"]["navidrome-basic"] = "nav-new.drv"
        plan = ci.select(head, self.base, ["modules/navidrome/plugins/gen/plugin.nix"])
        self.assertEqual(plan["checks"], ["navidrome-basic"])
        self.assertFalse(plan["production"])
        self.assertFalse(plan["gitops"])

    def test_transitive_dependents_and_new_checks_are_selected(self):
        head = copy.deepcopy(self.base)
        head["checks"] = {
            "navidrome-basic": "nav-new.drv",
            "radarr-basic": "radarr-new.drv",
            "new": "new.drv",
        }
        head["production"] = "new-system.drv"
        plan = ci.select(head, self.base, ["flake.lock"])
        self.assertEqual(plan["checks"], ["navidrome-basic", "new", "radarr-basic"])
        self.assertTrue(plan["production"])

    def test_unchanged_derivations_allow_empty_matrix(self):
        plan = ci.select(self.base, self.base, ["README.md"])
        self.assertEqual(plan["checks"], [])
        self.assertFalse(plan["production"])
        self.assertFalse(plan["gitops"])

    def test_tooling_changes_select_tooling(self):
        for path in [
            "scripts/provision-secrets.py",
            "pkgs/notifiarr/update.py",
            "renovate.json",
        ]:
            with self.subTest(path=path):
                self.assertTrue(ci.select(self.base, self.base, [path])["gitops"])

    def test_selector_changes_force_full_validation(self):
        for path in [
            ".github/workflows/ci.yml",
            "scripts/ci-plan.py",
            "tests/migration/test_ci_plan.py",
        ]:
            with self.subTest(path=path):
                plan = ci.select(self.base, self.base, [path])
                self.assertEqual(plan["checks"], sorted(self.base["checks"]))
                self.assertTrue(plan["production"])
                self.assertTrue(plan["gitops"])

    def test_head_evaluation_failure_is_not_a_skip(self):
        with patch.object(ci, "run", side_effect=["abc", "flake.lock"]), patch.object(
            ci, "manifest", side_effect=subprocess.CalledProcessError(1, "nix")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                ci.make_plan("abc")

    def test_base_evaluation_failure_runs_everything(self):
        with patch.object(ci, "run", return_value="abc"), patch.object(
            ci,
            "manifest",
            side_effect=[self.base, subprocess.CalledProcessError(1, "nix")],
        ):
            plan = ci.make_plan("abc")
        self.assertEqual(plan["checks"], sorted(self.base["checks"]))
        self.assertTrue(plan["production"])
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
                },
            },
            "checks": {"result": "success"},
            "production": {"result": "skipped"},
            "gitops": {"result": "skipped"},
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
        result = self.results()
        del result["prepare"]["outputs"]["production"]
        with self.assertRaises(ValueError):
            ci.verify(result)


if __name__ == "__main__":
    unittest.main()
