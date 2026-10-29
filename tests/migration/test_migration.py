import copy
import base64
import importlib.util
import os
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "capabilities/secrets"))


def module(name):
    spec = importlib.util.spec_from_file_location(
        name,
        ROOT
        / ("capabilities/secrets" if name.startswith("provision-") else "scripts")
        / (name + ".py"),
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


secrets = module("provision-secrets")
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


class Credentials(unittest.TestCase):
    def test_post_publication_sync_failure_restores_previous_generation(self):
        values = {key: "synthetic" for key in secrets.KEYS}
        values["SMB_CREDENTIALS"] = "username=test\npassword=synthetic\n"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "secrets"
            secrets.install(values, root)
            previous = os.readlink(root / "current")
            original_sync = os.fsync

            def fail_root_sync(fd):
                if os.fstat(fd).st_ino == root.stat().st_ino:
                    raise OSError("injected durability failure")
                original_sync(fd)

            with patch.object(secrets.os, "fsync", side_effect=fail_root_sync):
                with self.assertRaises(OSError):
                    secrets.install(dict(values, SONARR_API_KEY="changed"), root)
            self.assertEqual(os.readlink(root / "current"), previous)
            self.assertFalse((root / ".next").exists())

    def test_incomplete_and_mode_drift_replaced_atomically(self):
        values = {key: "synthetic" for key in secrets.KEYS}
        values["SMB_CREDENTIALS"] = "username=test\npassword=synthetic\n"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "secrets"
            secrets.install(values, root)
            for change in [
                lambda p: p.unlink(),
                lambda p: p.chmod(0o644),
                lambda p: p.parent.chmod(0o755),
            ]:
                old = os.readlink(root / "current")
                change(root / "current/sonarr")
                secrets.install(values, root)
                self.assertNotEqual(os.readlink(root / "current"), old)
                self.assertTrue(
                    secrets.valid_generation(root / "current", root, values)
                )
            before = os.readlink(root / "current")
            secrets.install(values, root)
            self.assertEqual(os.readlink(root / "current"), before)
            with patch.object(secrets.os, "replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    secrets.install(dict(values, SONARR_API_KEY="changed"), root)
            self.assertEqual(os.readlink(root / "current"), before)
            self.assertEqual((root / "current/sonarr").read_text(), "synthetic")

    def test_owner_drift_invalidates_generation(self):
        values = {key: "synthetic" for key in secrets.KEYS}
        values["SMB_CREDENTIALS"] = "username=test\npassword=synthetic\n"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "secrets"
            secrets.install(values, root)
            original = Path.lstat

            def drift(path, *args, **kwargs):
                result = original(path, *args, **kwargs)
                if path.name == "sonarr":
                    return SimpleNamespace(
                        st_mode=result.st_mode, st_uid=99999, st_gid=result.st_gid
                    )
                return result

            with patch.object(Path, "lstat", drift):
                self.assertFalse(
                    secrets.valid_generation(root / "current", root, values)
                )


if __name__ == "__main__":
    unittest.main()
