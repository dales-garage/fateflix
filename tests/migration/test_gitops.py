import gzip
from contextlib import ExitStack
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
    def run_monitoring_health(self, monitoring, *, connection=False, api_healthy=True):
        """Exercise check -> service -> arr without contacting a host or API."""
        manifest = {
            "services": {"sonarr": 8990, "plex": 32400, "seerr": 5055},
            "serviceCatalog": {
                name: {
                    "unit": name,
                    "healthPath": "/",
                    "apiVersion": "v3" if name == "sonarr" else None,
                    "aliasOf": None,
                }
                for name in ("sonarr", "plex", "seerr")
            },
        }
        if monitoring is not None:
            manifest["monitoring"] = {"notifiarr": monitoring}

        def response(url, headers=None, probe=False):
            if url.endswith("/system/status") and not api_healthy:
                raise ValueError("private API failure")
            if url.endswith("/notification"):
                return [{"implementation": "Notifiarr"}] if connection else []
            return 200 if probe else {}

        with ExitStack() as stack:
            mocks = {
                name: stack.enter_context(patch.object(health, name))
                for name in (
                    "active",
                    "nas",
                    "credentials",
                    "networking",
                    "plex",
                    "notifiarr",
                    "seerr",
                    "arr_advisory",
                    "write_json",
                )
            }
            mocks["arr_advisory"].return_value = {"status": "ok"}
            stack.enter_context(
                patch.object(health, "read_json", return_value=manifest)
            )
            stack.enter_context(
                patch.object(health.ops, "cached_probe", return_value={})
            )
            stack.enter_context(
                patch.object(health.Path, "read_text", return_value="boot")
            )
            stack.enter_context(
                patch.object(health.os.path, "realpath", return_value="system")
            )
            key = stack.enter_context(patch.object(health.ET, "parse"))
            key.return_value.findtext.return_value = "private-key"
            http = stack.enter_context(
                patch.object(health, "http", side_effect=response)
            )
            stack.enter_context(patch("builtins.print"))
            result = health.check()
        report = mocks["write_json"].call_args.args[1]
        return result, report, http, mocks

    def test_disabled_monitoring_keeps_arr_api_health_without_notifiarr(self):
        result, report, http, mocks = self.run_monitoring_health(False)
        self.assertEqual(result, 0)
        self.assertTrue(report["checks"]["sonarr"]["healthy"])
        http.assert_any_call(
            "http://127.0.0.1:8990/api/v3/system/status", {"X-Api-Key": "private-key"}
        )
        self.assertFalse(
            any(call.args[0].endswith("/notification") for call in http.call_args_list)
        )
        mocks["credentials"].assert_called_once_with(False)
        mocks["notifiarr"].assert_not_called()
        mocks["seerr"].assert_not_called()

    def test_enabled_or_legacy_monitoring_still_requires_arr_connection(self):
        for monitoring in (True, None):
            with self.subTest(monitoring=monitoring):
                result, report, _, mocks = self.run_monitoring_health(monitoring)
                self.assertEqual(result, 1)
                self.assertEqual(
                    report["checks"]["sonarr"],
                    {"healthy": False, "error_type": "ValueError"},
                )
                mocks["credentials"].assert_called_once_with(True)
                mocks["notifiarr"].assert_called_once_with()
                mocks["seerr"].assert_called_once_with(5055)
                result, report, _, _ = self.run_monitoring_health(
                    monitoring, connection=True
                )
                self.assertEqual(result, 0)
                self.assertTrue(report["healthy"])

    def test_disabled_monitoring_does_not_hide_an_arr_api_failure(self):
        result, report, _, _ = self.run_monitoring_health(False, api_healthy=False)
        self.assertEqual(result, 1)
        self.assertEqual(
            report["checks"]["sonarr"],
            {"healthy": False, "error_type": "ValueError"},
        )
        self.assertNotIn("private", str(report))

    def test_service_probe_uses_catalog_identity_path_and_api_version(self):
        spec = {"unit": "existing-unit", "healthPath": "/ready", "apiVersion": "v1"}
        with (
            patch.object(health, "active") as active,
            patch.object(health, "http") as http,
            patch.object(health, "arr") as arr,
        ):
            health.service("custom-arr", 1234, spec)
        active.assert_called_once_with("existing-unit")
        http.assert_called_once_with("http://127.0.0.1:1234/ready", probe=True)
        arr.assert_called_once_with("custom-arr", 1234, "v1", notifiarr_enabled=True)

    def test_non_arr_probe_does_not_guess_api_from_its_name(self):
        spec = {"unit": "podman-stash", "healthPath": "/", "apiVersion": None}
        with (
            patch.object(health, "active") as active,
            patch.object(health, "http"),
            patch.object(health, "arr") as arr,
        ):
            health.service("sonarr", 9999, spec)
        active.assert_called_once_with("podman-stash")
        arr.assert_not_called()

    def test_arr_advisory_names_come_from_catalog(self):
        manifest = {
            "serviceCatalog": {
                "new-arr": {"apiVersion": "v3"},
                "sonarr": {"apiVersion": None},
            }
        }
        self.assertEqual(health.arr_names(manifest), {"new-arr"})

    def test_mismatched_health_catalog_is_rejected_before_checks(self):
        with (
            patch.object(
                health,
                "read_json",
                return_value={"services": {"sonarr": 8990}, "serviceCatalog": {}},
            ),
            patch.object(health, "run_check") as run,
        ):
            with self.assertRaisesRegex(
                ValueError, "catalog and port manifest disagree"
            ):
                health.check()
        run.assert_not_called()

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

    def test_health_freshness_rejects_future_and_expired_reports(self):
        report = {
            "healthy": True,
            "checked": 1000,
            "boot_id": "boot",
            "system": "/nix/store/current",
        }
        for now, expected in (
            (999, False),
            (999.999, False),
            (1000, True),
            (1899.999, True),
            (1900, False),
            (2000, False),
        ):
            with self.subTest(now=now):
                self.assertEqual(
                    health.healthy(report, {}, {}, now, "boot", "/nix/store/current"),
                    expected,
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
