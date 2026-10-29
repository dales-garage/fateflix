import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("snapshot", ROOT / "snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class MigrationSnapshotTests(unittest.TestCase):
    def setUp(self):
        mask = os.umask(0o077)
        os.umask(mask)
        self.addCleanup(os.umask, mask)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source"
        self.destination = self.root / "snapshot"

    def run_snapshot(self, *, resume=False, sources=None):
        args = ["snapshot.py", str(self.destination)] + (["--resume"] if resume else [])
        with (
            patch.object(snapshot, "SOURCES", sources or {"sonarr": str(self.source)}),
            patch.object(snapshot.os, "geteuid", return_value=0),
            patch("sys.argv", args),
            patch("builtins.print"),
        ):
            snapshot.main()

    def manifest(self):
        return json.loads((self.destination / "snapshot.json").read_text())

    def assert_not_completed(self):
        manifest = self.destination / "snapshot.json"
        self.assertFalse(
            manifest.exists() and json.loads(manifest.read_text()).get("completed")
        )

    def seed_resume(self, services=None, **extra):
        self.destination.mkdir()
        value = {
            "started": "2026-10-29T00:00:00+00:00",
            "services": services or {},
        } | extra
        (self.destination / "snapshot.json").write_text(json.dumps(value))

    def test_missing_or_non_directory_source_never_completes(self):
        for kind in ("missing", "file"):
            with self.subTest(kind=kind):
                if kind == "file":
                    self.source.write_text("not a directory")
                with self.assertRaises((OSError, ValueError)):
                    self.run_snapshot()
                self.assert_not_completed()

    def test_unreadable_source_or_subdirectory_never_completes(self):
        self.source.mkdir()
        child = self.source / "nested"
        child.mkdir()
        original = os.scandir
        for inaccessible in (self.source, child):
            with self.subTest(path=inaccessible.name):

                def scan(path):
                    if Path(path) == inaccessible:
                        raise PermissionError("synthetic unreadable directory")
                    return original(path)

                with patch.object(snapshot.os, "scandir", side_effect=scan):
                    with self.assertRaises(PermissionError):
                        self.run_snapshot()
                self.assert_not_completed()
                if self.destination.exists():
                    shutil.rmtree(self.destination)

    def test_valid_copy_sqlite_and_completed_resume_are_preserved(self):
        self.source.mkdir()
        (self.source / "settings.json").write_text('{"synthetic": true}')
        with sqlite3.connect(self.source / "state.db") as db:
            db.execute("create table state(value text)")
            db.execute("insert into state values ('synthetic')")
        self.run_snapshot()
        self.assertTrue(self.manifest()["completed"])
        self.assertEqual(
            (self.destination / "sonarr/settings.json").read_text(),
            '{"synthetic": true}',
        )
        with sqlite3.connect(self.destination / "sonarr/state.db") as db:
            self.assertEqual(
                db.execute("select value from state").fetchone(), ("synthetic",)
            )
        before = (self.destination / "snapshot.json").read_bytes()
        shutil.rmtree(self.source)
        self.run_snapshot(resume=True)
        self.assertEqual((self.destination / "snapshot.json").read_bytes(), before)

    def test_partial_resume_keeps_completed_service_and_copies_pending_source(self):
        self.source.mkdir()
        (self.source / "settings").write_text("new state")
        previous_source = self.root / "retired-source"
        self.seed_resume({"radarr": {"source": str(previous_source), "databases": []}})
        (self.destination / "radarr").mkdir()
        (self.destination / "radarr/settings").write_text("previous state")
        self.run_snapshot(
            resume=True,
            sources={"radarr": str(previous_source), "sonarr": str(self.source)},
        )
        self.assertTrue(self.manifest()["completed"])
        self.assertEqual(
            (self.destination / "radarr/settings").read_text(), "previous state"
        )
        self.assertEqual(
            (self.destination / "sonarr/settings").read_text(), "new state"
        )

    def test_missing_or_symlinked_completed_service_is_not_trusted(self):
        self.seed_resume({"sonarr": {"source": str(self.source), "databases": []}})
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    (self.destination / "sonarr").symlink_to(self.root)
                with self.assertRaises(ValueError):
                    self.run_snapshot(resume=True)
                self.assert_not_completed()

    def test_invalid_resume_metadata_is_rejected_without_rewriting(self):
        self.seed_resume()
        manifest = self.destination / "snapshot.json"
        for value in (
            [],
            {"services": {}},
            {"started": "now", "services": []},
            {"started": "now", "services": {"unknown": {}}},
            {
                "started": "now",
                "services": {"sonarr": {"source": "/wrong", "databases": []}},
            },
            {"started": "now", "services": {}, "completed": "now"},
        ):
            with self.subTest(value=value):
                original = json.dumps(value)
                manifest.write_text(original)
                with self.assertRaises(ValueError):
                    self.run_snapshot(resume=True)
                self.assertEqual(manifest.read_text(), original)

    def test_symlinked_resume_root_or_manifest_is_not_trusted(self):
        self.seed_resume()
        original = self.destination / "snapshot.json"
        saved = original.read_bytes()
        renamed = self.root / "renamed"
        self.destination.rename(renamed)
        self.destination.symlink_to(renamed)
        with self.assertRaises(ValueError):
            self.run_snapshot(resume=True)
        self.assertEqual(original.read_bytes(), saved)
        self.destination.unlink()
        renamed.rename(self.destination)
        other = self.root / "manifest.json"
        original.rename(other)
        original.symlink_to(other)
        with self.assertRaises(ValueError):
            self.run_snapshot(resume=True)
        self.assertEqual(other.read_bytes(), saved)

    def test_failed_manifest_publication_preserves_previous_record(self):
        self.seed_resume()
        target = self.destination / "snapshot.json"
        original = target.read_bytes()
        with patch.object(
            snapshot.os, "replace", side_effect=OSError("synthetic write failure")
        ):
            with self.assertRaises(OSError):
                snapshot.write_manifest(
                    self.destination, {"completed": "not published"}
                )
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(
            sorted(p.name for p in self.destination.iterdir()), ["snapshot.json"]
        )


if __name__ == "__main__":
    unittest.main()
