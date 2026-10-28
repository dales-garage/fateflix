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
    def test_startup_failure_is_retried_until_ready(self):
        with (
            patch.object(health, "check", side_effect=[1, 0]) as check,
            patch.object(health.time, "monotonic", return_value=0),
            patch.object(health.time, "sleep") as sleep,
        ):
            self.assertEqual(health.check_until_ready(120), 0)
            self.assertEqual(check.call_count, 2)
            sleep.assert_called_once_with(10)

    def test_persistent_failure_remains_failed_after_grace_period(self):
        with (
            patch.object(health, "check", return_value=1),
            patch.object(health.time, "monotonic", side_effect=[0, 120]),
            patch.object(health.time, "sleep") as sleep,
        ):
            self.assertEqual(health.check_until_ready(120), 1)
            sleep.assert_not_called()

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
    def test_formatting_only_update_is_noop(self):
        path = "integrations/nixflix/plugins/navidrome/gen/lyrics-plugin.nix"
        with (
            patch.object(updates, "changed_files", side_effect=[[path], []]),
            patch.object(updates.Path, "exists", return_value=True),
            patch.object(updates, "run"),
        ):
            self.assertEqual(updates.formatted_changes([path]), [])

    def test_formatter_cannot_publish_unrelated_changes(self):
        path = "pkgs/notifiarr/default.nix"
        with (
            patch.object(
                updates, "changed_files", side_effect=[[path], [path, "flake.nix"]]
            ),
            patch.object(updates.Path, "exists", return_value=True),
            patch.object(updates, "run"),
        ):
            with self.assertRaisesRegex(RuntimeError, "outside the updater allowlist"):
                updates.formatted_changes([path])

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

    def test_retired_upstream_publisher_fails_before_running_commands(self):
        with (
            patch("sys.argv", ["update-pr.py", "upstream"]),
            patch.object(updates, "run") as run,
        ):
            with self.assertRaises(SystemExit) as error:
                updates.main()
        self.assertEqual(error.exception.code, 2)
        run.assert_not_called()
        self.assertNotIn("upstream", updates.UPDATERS)

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
