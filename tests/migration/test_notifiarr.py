import contextlib
import copy
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations/nixflix/compatibility/notifiarr"))
from render import resolve

spec = importlib.util.spec_from_file_location(
    "notifiarr_connections", ROOT / "scripts/configure-notifiarr.py"
)
connections = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connections)


class NotifiarrTest(unittest.TestCase):
    def test_local_reconciliation_does_not_resolve_or_call_plex_cloud(self):
        raw = {
            "apiKey": "private",
            "arr": [],
            "seerr": {},
            "bazarr": [],
            "plex": {"token": {"_secret": "/unavailable/cloud/token"}},
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "connections.json"
            manifest.write_text(json.dumps(raw))
            with patch.object(
                sys, "argv", ["configure-notifiarr.py", str(manifest), "--local-only"]
            ), patch.object(connections, "connect_seerr") as local, patch.object(
                connections, "connect_plex"
            ) as cloud, contextlib.redirect_stdout(
                io.StringIO()
            ):
                connections.main()
            local.assert_called_once_with({}, "private")
            cloud.assert_not_called()

    def test_cloud_failure_remains_a_failure_without_touching_local_connections(self):
        raw = {
            "plex": {"token": "private-canary"},
            "plexWebhook": "http://127.0.0.1:5454/plex",
            "arr": [{"api_key": {"_secret": "/unavailable/local/key"}}],
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "connections.json"
            manifest.write_text(json.dumps(raw))
            with patch.object(
                sys,
                "argv",
                ["configure-notifiarr.py", str(manifest), "--plex-webhooks-only"],
            ), patch.object(
                connections, "connect_plex", side_effect=ValueError("private-canary")
            ) as cloud, patch.object(
                connections, "connect_arr"
            ) as local:
                with self.assertRaises(SystemExit) as error:
                    connections.main()
            cloud.assert_called_once()
            local.assert_not_called()
            self.assertIn("plex-webhooks", str(error.exception))
            self.assertNotIn("private-canary", str(error.exception))

    def test_extended_outage_does_not_exhaust_future_timer_attempts(self):
        from unittest.mock import Mock

        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        job = Mock(side_effect=TimeoutError("private-url"))
        with patch.object(
            connections.time, "monotonic", side_effect=lambda: clock[0]
        ), patch.object(connections.time, "sleep", side_effect=sleep), patch(
            "builtins.print"
        ):
            for _ in range(4):
                started = clock[0]
                self.assertEqual(connections.reconcile(("sonarr", job)), "sonarr")
                self.assertLessEqual(clock[0] - started, 90)
            job.side_effect = None
            self.assertIsNone(connections.reconcile(("sonarr", job)))
        self.assertGreater(job.call_count, 12)

    def test_slow_cold_start_recovers_within_the_same_invocation(self):
        clock = [0.0]

        def job():
            if clock[0] < 65:
                raise connections.urllib.error.URLError("private-url")

        def sleep(seconds):
            clock[0] += seconds

        with patch.object(
            connections.time, "monotonic", side_effect=lambda: clock[0]
        ), patch.object(connections.time, "sleep", side_effect=sleep), patch(
            "builtins.print"
        ):
            self.assertIsNone(connections.reconcile(("bazarr", job)))
        self.assertGreaterEqual(clock[0], 65)
        self.assertLessEqual(clock[0], 90)

    def test_permanent_http_errors_do_not_retry_and_transient_errors_do(self):
        from unittest.mock import Mock

        error = connections.urllib.error.HTTPError
        permanent = Mock(side_effect=error("private-url", 401, "private", {}, None))
        with patch.object(connections.time, "sleep") as sleep:
            self.assertEqual(connections.reconcile(("sonarr", permanent)), "sonarr")
            sleep.assert_not_called()
        self.assertEqual(permanent.call_count, 1)
        transient = Mock(
            side_effect=[error("private-url", 503, "private", {}, None), None]
        )
        with patch.object(connections.time, "sleep"), patch("builtins.print"):
            self.assertIsNone(connections.reconcile(("sonarr", transient)))
        self.assertEqual(transient.call_count, 2)

    def test_queued_jobs_obey_the_shared_retry_deadline(self):
        from unittest.mock import Mock

        job = Mock()
        with patch.object(connections.time, "monotonic", return_value=121):
            self.assertEqual(
                connections.reconcile(("bazarr", job), deadline=120), "bazarr"
            )
        job.assert_not_called()

    def test_runtime_secrets_and_missing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            xml = Path(directory) / "config.xml"
            xml.write_text("<Config><ApiKey>arr-key</ApiKey></Config>")
            plex = Path(directory) / "Preferences.xml"
            plex.write_text('<Preferences PlexOnlineToken="plex-key"/>')
            data = {
                "sonarr": [
                    {
                        "api_key": {
                            "_secret": str(xml),
                            "format": "xml",
                            "key": ["ApiKey"],
                        }
                    }
                ],
                "plex": {
                    "token": {
                        "_secret": str(plex),
                        "format": "xml",
                        "key": ["@PlexOnlineToken"],
                    }
                },
            }
            self.assertEqual(
                resolve(data),
                {"sonarr": [{"api_key": "arr-key"}], "plex": {"token": "plex-key"}},
            )
            xml.write_text("<Config/>")
            with self.assertRaises(ValueError):
                resolve(data)

    def test_update_existing_without_duplicates_or_mutation(self):
        existing = [
            {
                "id": 7,
                "name": "Existing Notifiarr",
                "implementation": "Notifiarr",
                "fields": [{"name": "aPIKey", "value": "old"}],
                "supportsOnGrab": True,
                "onGrab": False,
                "tags": [4],
            }
        ]
        original = copy.deepcopy(existing)
        current, desired = connections.notification([], existing, "new")
        self.assertEqual(existing, original)
        self.assertEqual(desired["id"], 7)
        self.assertEqual(desired["tags"], [4])
        self.assertTrue(desired["onGrab"])
        self.assertEqual(desired["fields"][0]["value"], "new")
        current, again = connections.notification([], [desired], "new")
        self.assertEqual(current, again)
        with self.assertRaises(ValueError):
            connections.notification([], existing * 2, "new")

    def test_seerr_payload_is_default_structured_event(self):
        payload = json.loads(connections.seerr_payload())
        self.assertEqual(payload["notification_type"], "{{notification_type}}")
        self.assertIn("{{request}}", payload)
        self.assertIn("{{issue}}", payload)
        self.assertIn("{{media}}", payload)

    def test_masked_keys_skip_writes_but_rotation_is_applied(self):
        app = {
            "name": "sonarr",
            "url": "http://localhost",
            "apiVersion": "v3",
            "api_key": "app-key",
        }
        current = [
            {
                "id": 1,
                "name": "Notifiarr",
                "implementation": "Notifiarr",
                "fields": [{"name": "apiKey", "value": "********"}],
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "sonarr.key.sha256"
            import hashlib

            marker.write_text(hashlib.sha256(b"old-key").hexdigest())
            with patch.object(
                connections, "Path", return_value=Path(directory)
            ), patch.object(connections, "backup"), patch.object(
                connections, "request", side_effect=[current, []]
            ) as request:
                connections.connect_arr(app, "old-key")
                self.assertEqual(request.call_count, 2)
            with patch.object(
                connections, "Path", return_value=Path(directory)
            ), patch.object(connections, "backup"), patch.object(
                connections, "request", side_effect=[current, [], {}]
            ) as request:
                connections.connect_arr(app, "new-key")
                self.assertEqual(request.call_args.args[2], "PUT")
                self.assertEqual(
                    marker.read_text(), hashlib.sha256(b"new-key").hexdigest()
                )

    def test_seerr_preserves_defaults_and_is_idempotent(self):
        app = {"url": "http://localhost", "api_key": "unused"}
        current = {
            "enabled": True,
            "embedPoster": True,
            "types": 4094,
            "options": {
                "webhookUrl": "https://notifiarr.com/api/v1/notification/seerr/key",
                "jsonPayload": connections.seerr_payload(),
                "customHeaders": [],
                "supportVariables": False,
            },
        }
        with patch.object(connections, "request", return_value=current) as request:
            connections.connect_seerr(app, "key")
            self.assertEqual(request.call_count, 1)
        current["options"]["jsonPayload"] = json.loads(
            current["options"]["jsonPayload"]
        )
        with patch.object(connections, "request", return_value=current) as request:
            connections.connect_seerr(app, "key")
            self.assertEqual(request.call_count, 1)

    def test_preserves_active_unrelated_webhooks(self):
        app = {"url": "http://localhost", "api_key": "unused", "name": "bazarr"}
        with patch.object(
            connections,
            "request",
            return_value={
                "enabled": True,
                "options": {"webhookUrl": "https://example.com"},
            },
        ) as request:
            with self.assertRaises(ValueError):
                connections.connect_seerr(app, "unused")
            self.assertEqual(request.call_count, 1)
        with patch.object(
            connections,
            "request",
            return_value={
                "notifications": {
                    "providers": [
                        {"name": "JSON", "enabled": True, "url": "jsons://example.com"}
                    ]
                }
            },
        ) as request:
            with self.assertRaises(ValueError):
                connections.connect_bazarr(app, "unused")
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
