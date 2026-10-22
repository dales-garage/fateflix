import gzip
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


health = load("health", "scripts/gitops-health.py")
updates = load("updates", "scripts/update-pr.py")
notifiarr = load("notifiarr_update", "pkgs/notifiarr/update.py")


class HealthTests(unittest.TestCase):
    def test_proxy_probe_uses_authenticated_api_without_login_redirect(self):
        with (
            patch.object(health.Path, "read_text", return_value="production\n"),
            patch.object(health, "active"),
            patch.object(health.ET, "parse") as config,
            patch.object(health, "http", return_value={"appName": "Sonarr"}) as request,
        ):
            config.return_value.findtext.return_value = "private-key"
            health.networking()
            request.assert_called_once_with(
                "http://127.0.0.1/api/v3/system/status",
                {"Host": "sonarr.vm.internal", "X-Api-Key": "private-key"},
            )

    def test_stale_or_previous_boot_or_generation_is_unhealthy(self):
        report = {
            "healthy": True,
            "checked": 1000,
            "boot_id": "boot",
            "system": "/nix/store/current",
        }
        self.assertTrue(
            health.healthy(report, {}, {}, 1001, "boot", "/nix/store/current")
        )
        self.assertFalse(
            health.healthy(report, {}, {}, 2000, "boot", "/nix/store/current")
        )
        self.assertFalse(
            health.healthy(report, {}, {}, 1001, "other", "/nix/store/current")
        )
        self.assertFalse(health.healthy(report, {}, {}, 1001, "boot", "/nix/store/old"))
        self.assertFalse(
            health.healthy(
                report, {"status": "failed"}, {}, 1001, "boot", "/nix/store/current"
            )
        )
        self.assertFalse(
            health.healthy(
                report, {}, {"status": "failed"}, 1001, "boot", "/nix/store/current"
            )
        )

    def test_exceptions_never_publish_secrets(self):
        def failure():
            raise ValueError("https://example.invalid/?apikey=secret")

        name, result = health.run_check(("probe", failure))
        self.assertEqual(name, "probe")
        self.assertEqual(result, {"healthy": False, "error_type": "ValueError"})

    def test_failed_hook_does_not_claim_deployment(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(health, "STATE", Path(directory)),
        ):
            with patch.dict(
                "os.environ",
                {
                    "COMIN_PHASE": "deploy",
                    "COMIN_STATUS": "failed",
                    "COMIN_GIT_SHA": "bad",
                },
            ):
                health.hook()
            self.assertFalse((Path(directory) / "deployed.json").exists())
            self.assertEqual(
                health.read_json(Path(directory) / "deploy.json")["status"], "failed"
            )


class UpdateTests(unittest.TestCase):
    def test_allowlist_rejects_workflows_and_unrelated_files(self):
        patterns = updates.UPDATERS["notifiarr"][1]
        self.assertTrue(
            updates.allowed_changes(["pkgs/notifiarr/default.nix"], patterns)
        )
        self.assertFalse(
            updates.allowed_changes(
                ["pkgs/notifiarr/default.nix", ".github/workflows/ci.yml"], patterns
            )
        )

    def test_already_merged_upstream_is_noop(self):
        with patch.object(updates, "run") as run:
            run.return_value.stdout = "abc\n"
            run.return_value.returncode = 0
            self.assertFalse(updates.sync_upstream())
            self.assertFalse(
                any(c.args[:2] == ("git", "merge") for c in run.call_args_list)
            )

    def test_conflict_aborts_without_pushing(self):
        def fake(*args, **kwargs):
            from subprocess import CompletedProcess

            code = (
                1
                if args[:2] in [("git", "merge-base"), ("git", "merge")]
                and "--abort" not in args
                else 0
            )
            return CompletedProcess(args, code, stdout="conflicted.nix\n")

        with patch.object(updates, "run", side_effect=fake) as run:
            with self.assertRaises(RuntimeError):
                updates.sync_upstream()
            self.assertIn(
                ("git", "merge", "--abort"), [c.args for c in run.call_args_list]
            )
            self.assertFalse(
                any(c.args[:2] == ("git", "push") for c in run.call_args_list)
            )

    def test_release_assets_match_architecture_and_digest(self):
        binary = bytearray(64)
        binary[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", binary, 18, 62)
        data = gzip.compress(binary)
        self.assertTrue(notifiarr.release_hash(data, 62).startswith("sha256-"))
        with self.assertRaises(ValueError):
            notifiarr.release_hash(data, 183)
        with self.assertRaises(ValueError):
            notifiarr.release_hash(data, 62, "sha256:wrong")


if __name__ == "__main__":
    unittest.main()
