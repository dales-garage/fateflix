import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "capabilities/secrets/passage_store.py"
spec = importlib.util.spec_from_file_location("passage_store", SOURCE)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


class PassageMigration(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.umask, os.umask(0o077))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "gpg"
        self.source.mkdir()
        self.destination = self.root / "age/store"
        self.identity = self.root / "age/identities"
        self.identity.parent.mkdir()
        self.identity.write_bytes(b"synthetic identity")
        self.identity.chmod(0o600)
        environment = patch.dict(
            os.environ,
            {
                "PASSWORD_STORE_DIR": str(self.source),
                "PASSAGE_DIR": str(self.destination),
                "PASSAGE_IDENTITIES_FILE": str(self.identity),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.original = {"nested/KEY": b"  first\nsecond\x00\n\n", "OTHER": b"last"}
        for name, value in self.original.items():
            path = self.source / (name + ".gpg")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original ciphertext")

    def crypto(self, args, *, data=None, env=None):
        if args[0] == "/original/pass":
            return self.original[args[-1]]
        path = Path(env["PASSAGE_DIR"]) / (args[-1] + ".age")
        if args[1] == "show":
            return path.read_bytes().removeprefix(b"test ciphertext:")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(b"test ciphertext:" + data)
        return b""

    def test_preserves_bytes_names_and_original_ciphertexts_and_is_repeatable(self):
        with patch.object(store, "command", side_effect=self.crypto):
            self.assertEqual(store.migrate("/original/pass"), 2)
            self.assertEqual(store.migrate("/original/pass"), 2)
        for name, value in self.original.items():
            self.assertEqual(
                (self.destination / (name + ".age")).read_bytes(),
                b"test ciphertext:" + value,
            )
            self.assertEqual(
                (self.source / (name + ".gpg")).read_bytes(), b"original ciphertext"
            )
        self.assertEqual(list(self.destination.parent.glob(".migration-*")), [])

    def test_decryption_failure_does_not_publish_partial_vault(self):
        def fail(args, **kwargs):
            if args == ["/original/pass", "show", "nested/KEY"]:
                raise subprocess.CalledProcessError(1, args, stderr=b"sensitive detail")
            return self.crypto(args, **kwargs)

        with patch.object(store, "command", side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                store.migrate("/original/pass")
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.glob(".migration-*")), [])

    def test_failed_round_trip_does_not_publish_vault(self):
        def corrupt(args, **kwargs):
            value = self.crypto(args, **kwargs)
            return b"corrupt" if args[:2] == ["passage", "show"] else value

        with patch.object(store, "command", side_effect=corrupt):
            with self.assertRaises(ValueError):
                store.migrate("/original/pass")
        self.assertFalse(self.destination.exists())

    def test_existing_newer_age_value_is_never_overwritten(self):
        with patch.object(store, "command", side_effect=self.crypto):
            store.migrate("/original/pass")
            path = self.destination / "OTHER.age"
            path.write_bytes(b"test ciphertext:newer")
            with self.assertRaises(ValueError):
                store.migrate("/original/pass")
            self.assertEqual(path.read_bytes(), b"test ciphertext:newer")

    def test_symlink_source_is_rejected(self):
        (self.source / "LINK.gpg").symlink_to(self.source / "OTHER.gpg")
        with patch.object(store, "command") as command:
            with self.assertRaises(ValueError):
                store.migrate("/original/pass")
            command.assert_not_called()

    def test_import_validates_all_input_before_creating_identity_or_writing(self):
        for values in ([], {}, {"GOOD": "value", "../BAD": "value"}, {"KEY": 3}):
            with self.subTest(values=values), patch.object(store, "command") as command:
                with self.assertRaises(ValueError):
                    store.import_values(values)
                command.assert_not_called()
                self.assertFalse(self.destination.exists())

    def test_shared_identity_permissions_are_rejected(self):
        self.identity.chmod(0o644)
        with self.assertRaises(ValueError):
            store.initialize(self.identity)


if __name__ == "__main__":
    unittest.main()
