import importlib.util
import io
import os
from pathlib import Path
import sys
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "capabilities/secrets"))
spec = importlib.util.spec_from_file_location(
    "notifiarr_provision", ROOT / "capabilities/secrets/provision-notifiarr.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

KEY = "00000000-0000-0000-0000-000000000000"
ROTATED = "11111111-1111-1111-1111-111111111111"


class NotifiarrProvisioningTests(unittest.TestCase):
    def setUp(self):
        mask = os.umask(0o077)
        os.umask(mask)
        self.addCleanup(os.umask, mask)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "credentials"
        self.target = self.root / "notifiarr-api-key"

    def test_creation_rotation_and_valid_idempotence(self):
        installer.install(KEY, self.root)
        first = self.target.stat().st_ino
        installer.install(KEY, self.root)
        self.assertEqual(self.target.stat().st_ino, first)
        installer.install(ROTATED, self.root)
        self.assertEqual(self.target.read_text(), ROTATED)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_unchanged_value_repairs_file_and_directory_mode_drift(self):
        self.root.mkdir(mode=0o700)
        self.target.write_text(KEY)
        self.root.chmod(0o755)
        self.target.chmod(0o644)

        def location(value):
            return (
                self.root if str(value) == "/var/lib/nixflix-secrets" else Path(value)
            )

        uid = os.geteuid()
        first = True

        def effective_uid():
            nonlocal first
            if first:
                first = False
                return 0  # Exercise the root-only CLI with user-owned test fixtures.
            return uid

        with (
            patch.object(installer, "installed_role"),
            patch.object(installer, "Path", side_effect=location),
            patch.object(installer.os, "geteuid", side_effect=effective_uid),
            patch.object(sys, "argv", ["provision-notifiarr.py", "install"]),
            patch.object(sys, "stdin", io.StringIO(KEY)),
        ):
            installer.main()
        self.assertEqual(self.target.read_text(), KEY)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        inode = self.target.stat().st_ino
        installer.install(KEY, self.root)
        self.assertEqual(self.target.stat().st_ino, inode)

    def test_invalid_key_rejected_before_creating_directory(self):
        with self.assertRaises(ValueError):
            installer.install("invalid synthetic input", self.root)
        self.assertFalse(self.root.exists())

    def test_symlink_root_rejected_without_touching_destination(self):
        other = self.root.parent / "other"
        other.mkdir(mode=0o755)
        other.chmod(0o755)
        self.root.symlink_to(other)
        with self.assertRaises(ValueError):
            installer.install(KEY, self.root)
        self.assertEqual(other.stat().st_mode & 0o777, 0o755)
        self.assertEqual(list(other.iterdir()), [])

    def test_symlink_key_rejected_without_touching_destination(self):
        self.root.mkdir(mode=0o700)
        other = self.root.parent / "other-key"
        other.write_text(KEY)
        other.chmod(0o644)
        self.target.symlink_to(other)
        with self.assertRaises(ValueError):
            installer.install(KEY, self.root)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(other.stat().st_mode & 0o777, 0o644)
        self.assertEqual(other.read_text(), KEY)

    def test_non_regular_key_is_rejected(self):
        self.root.mkdir(mode=0o700)
        self.target.mkdir()
        with self.assertRaises(ValueError):
            installer.install(KEY, self.root)
        self.assertTrue(self.target.is_dir())

    def test_symlink_lock_is_rejected_without_touching_its_destination(self):
        self.root.mkdir(mode=0o700)
        other = self.root.parent / "other-lock"
        other.write_text("unchanged")
        other.chmod(0o644)
        (self.root / ".notifiarr.lock").symlink_to(other)
        with self.assertRaises(OSError):
            installer.install(KEY, self.root)
        self.assertEqual(other.read_text(), "unchanged")
        self.assertEqual(other.stat().st_mode & 0o777, 0o644)
        self.assertFalse(self.target.exists())

    def test_untrusted_root_or_key_owner_is_rejected(self):
        installer.install(KEY, self.root)
        original = Path.lstat
        for unsafe in (self.root, self.target):
            with self.subTest(path=unsafe.name):

                def metadata(path, *args, **kwargs):
                    result = original(path, *args, **kwargs)
                    if path == unsafe:
                        return SimpleNamespace(
                            st_mode=result.st_mode, st_uid=99999, st_gid=result.st_gid
                        )
                    return result

                with patch.object(Path, "lstat", metadata):
                    with self.assertRaises(ValueError):
                        installer.install(ROTATED, self.root)
                self.assertEqual(self.target.read_text(), KEY)

    def test_failed_file_sync_or_publication_preserves_previous_key(self):
        installer.install(KEY, self.root)
        original_sync = os.fsync

        def fail_file_sync(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("synthetic file sync failure")
            return original_sync(fd)

        for action in ("fsync", "replace"):
            with self.subTest(action=action):
                failure = (
                    fail_file_sync
                    if action == "fsync"
                    else OSError("synthetic replace failure")
                )
                with patch.object(installer.os, action, side_effect=failure):
                    with self.assertRaises(OSError):
                        installer.install(ROTATED, self.root)
                self.assertEqual(self.target.read_text(), KEY)
                self.assertFalse(
                    any(p.name.startswith(".notifiarr-") for p in self.root.iterdir())
                )

    def test_parent_sync_failure_rolls_back_existing_or_new_key(self):
        original_replace = os.replace
        original_sync = os.fsync
        for existing in (True, False):
            with self.subTest(existing=existing):
                if existing:
                    installer.install(KEY, self.root)
                else:
                    self.target.unlink(missing_ok=True)
                published = False
                failed = False

                def replace(source, destination):
                    nonlocal published
                    result = original_replace(source, destination)
                    if destination == self.target:
                        published = True
                    return result

                def sync(fd):
                    nonlocal failed
                    if (
                        published
                        and not failed
                        and os.fstat(fd).st_ino == self.root.stat().st_ino
                    ):
                        failed = True
                        raise OSError("synthetic parent sync failure")
                    return original_sync(fd)

                with patch.object(
                    installer.os, "replace", side_effect=replace
                ), patch.object(installer.os, "fsync", side_effect=sync):
                    with self.assertRaises(OSError):
                        installer.install(ROTATED, self.root)
                self.assertTrue(failed)
                if existing:
                    self.assertEqual(self.target.read_text(), KEY)
                else:
                    self.assertFalse(self.target.exists())
                self.assertFalse(
                    any(p.name.startswith(".notifiarr-") for p in self.root.iterdir())
                )


if __name__ == "__main__":
    unittest.main()
