import copy
import base64
import importlib.util
import os
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / (name + ".py")
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


secrets = module("provision-secrets")
profiles = module("reassign-profiles")
notifications = module("provision-notifications")
seerr_notifications = module("configure-seerr-notifications")


class NotificationProvisioning(unittest.TestCase):
    def test_seerr_payload_encoding_and_preserved_destinations(self):
        settings = {
            "sonarr": [{"id": 1, "apiKey": "synthetic"}],
            "main": {"apiKey": "synthetic"},
        }
        result = seerr_notifications.configure(
            copy.deepcopy(settings), "https://requests.example.test"
        )
        self.assertEqual(settings["sonarr"], result["sonarr"])
        self.assertEqual(settings["main"]["apiKey"], result["main"]["apiKey"])
        webhook = result["notifications"]["agents"]["webhook"]
        self.assertFalse(webhook["enabled"])
        payload = json.loads(
            json.loads(base64.b64decode(webhook["options"]["jsonPayload"]))
        )
        self.assertIn("https://requests.example.test/requests", payload["body"])
        self.assertNotIn("synthetic", json.dumps(payload))

    def test_both_destinations_atomic_rotation_and_missing_secret(self):
        values = {
            "DISCORD_APPRISE_URL": "discord://123/synthetic",
            "MATRIX_APPRISE_URL": "matrixs://synthetic@example.test/!room",
        }
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "credentials"
            notifications.install(values, root)
            target = root / "notifications.json"
            before = target.read_bytes()
            inode = target.stat().st_ino
            notifications.install(values, root)
            self.assertEqual(inode, target.stat().st_ino)
            self.assertEqual(0o600, target.stat().st_mode & 0o777)
            with self.assertRaises(ValueError):
                notifications.install(dict(values, MATRIX_APPRISE_URL=""), root)
            self.assertEqual(before, target.read_bytes())
            notifications.install(
                dict(values, DISCORD_APPRISE_URL="discord://123/rotated"), root
            )
            self.assertNotEqual(before, target.read_bytes())


class Provisioning(unittest.TestCase):
    def test_atomic_idempotent_and_missing_secret(self):
        values = {key: "synthetic-key" for key in secrets.KEYS}
        values["SMB_CREDENTIALS"] = "username=test\npassword=synthetic\n"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "credentials"
            secrets.install(values, root)
            first = os.readlink(root / "current")
            secrets.install(values, root)
            self.assertEqual(first, os.readlink(root / "current"))
            self.assertEqual(0o700, root.stat().st_mode & 0o777)
            for file in (root / "current").iterdir():
                self.assertEqual(0o600, file.stat().st_mode & 0o777)
            with self.assertRaises(ValueError):
                secrets.install(dict(values, SONARR_API_KEY=""), root)
            self.assertEqual(first, os.readlink(root / "current"))
            secrets.install(dict(values, SONARR_API_KEY="rotated"), root)
            self.assertNotEqual(first, os.readlink(root / "current"))
            self.assertEqual("rotated", (root / "current" / "sonarr").read_text())


class ProfileMigration(unittest.TestCase):
    def run_migration(self, fail=False):
        titles = [
            {"id": 1, "path": "/data/a", "monitored": False, "qualityProfileId": 1},
            {"id": 2, "path": "/data/b", "monitored": True, "qualityProfileId": 1},
        ]
        calls = []

        def call(method, path, payload=None):
            calls.append((method, path, payload))
            if (method, path) == ("GET", "qualityprofile"):
                return [{"id": 1, "name": "obsolete"}, {"id": 2, "name": "desired"}]
            if (method, path) == ("GET", "importlist"):
                return []
            if (method, path) == ("GET", "series"):
                return copy.deepcopy(titles)
            if method == "PUT":
                self.assertTrue(path.endswith("?moveFiles=false"))
                if fail and payload["id"] == 2:
                    raise OSError("simulated API failure")
                titles[payload["id"] - 1] = payload
            elif method == "DELETE":
                self.assertTrue(all(t["qualityProfileId"] == 2 for t in titles))

        if fail:
            with self.assertRaises(OSError):
                profiles.migrate(call, "series", "desired")
            self.assertFalse(any(m == "DELETE" for m, _, _ in calls))
        else:
            self.assertEqual(2, profiles.migrate(call, "series", "desired"))
            self.assertEqual([False, True], [t["monitored"] for t in titles])
            self.assertEqual(["/data/a", "/data/b"], [t["path"] for t in titles])
            self.assertEqual(("DELETE", "qualityprofile/1", None), calls[-1])
        self.assertFalse(any("command" in path for _, path, _ in calls))

    def test_import_list_and_collection_references(self):
        lists = [{"id": 10, "qualityProfileId": 1, "enableAutomaticAdd": False}]
        collections = [
            {
                "id": 20,
                "qualityProfileId": 1,
                "monitored": True,
                "rootFolderPath": "/data/movies",
            }
        ]
        deleted = []

        def call(method, path, payload=None):
            if method == "GET":
                return copy.deepcopy(
                    {
                        "qualityprofile": [
                            {"id": 1, "name": "old"},
                            {"id": 2, "name": "desired"},
                        ],
                        "movie": [],
                        "importlist": lists,
                        "collection": collections,
                    }[path]
                )
            if method == "PUT":
                if path.startswith("importlist/"):
                    self.assertFalse(payload["enableAutomaticAdd"])
                    lists[0] = payload
                elif path == "collection/20":
                    self.assertTrue(payload["monitored"])
                    self.assertEqual("/data/movies", payload["rootFolderPath"])
                    collections[0] = payload
                else:
                    self.fail("Unexpected update or bulk refresh")
            if method == "DELETE":
                self.assertEqual(2, lists[0]["qualityProfileId"])
                self.assertEqual(2, collections[0]["qualityProfileId"])
                deleted.append(path)

        profiles.migrate(call, "movie", "desired")
        self.assertEqual(["qualityprofile/1"], deleted)

    def test_reassign_verify_delete(self):
        self.run_migration()

    def test_partial_failure_never_deletes(self):
        self.run_migration(fail=True)


if __name__ == "__main__":
    unittest.main()
