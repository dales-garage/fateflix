import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "modules/notifiarr"))
from render import resolve

spec = importlib.util.spec_from_file_location(
    "notifiarr_connections", ROOT / "scripts/configure-notifiarr.py"
)
connections = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connections)


class NotifiarrTest(unittest.TestCase):
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
