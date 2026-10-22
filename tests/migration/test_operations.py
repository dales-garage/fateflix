"""Fault injection stays local; all NAS and application calls are mocked."""

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import nixflix_ops as ops
import nixflix_retention as retention


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


health = load("operations_health", "gitops-health.py")


class Capacity(unittest.TestCase):
    def measure(self, available, files=0, free=0, inodes=True):
        fs = SimpleNamespace(
            f_bavail=available, f_frsize=1, f_files=files, f_favail=free
        )
        with patch.object(ops.os, "statvfs", return_value=fs):
            return ops.capacity("/unused", {"warning": 100, "critical": 50}, inodes)

    def test_strict_boundaries(self):
        for value, expected in [
            (101, "ok"),
            (100, "ok"),
            (99, "warning"),
            (50, "warning"),
            (49, "critical"),
        ]:
            self.assertEqual(self.measure(value)["status"], expected)

    def test_only_meaningful_inode_totals(self):
        self.assertNotIn("inode_free_fraction", self.measure(1000))
        self.assertNotIn("inode_free_fraction", self.measure(1000, 2**64 - 1, 0))
        self.assertNotIn("inode_free_fraction", self.measure(1000, 100, 0, False))
        self.assertEqual(self.measure(1000, 100, 4)["status"], "critical")
        self.assertEqual(self.measure(1000, 100, 5)["status"], "warning")
        self.assertEqual(self.measure(1000, 100, 10)["status"], "ok")

    def test_advisory_levels_and_unknown(self):
        for state, warning, critical in [
            ("ok", True, True),
            ("warning", False, True),
            ("critical", False, False),
            ("unknown", False, False),
        ]:
            with patch.object(
                ops,
                "cached_probe",
                return_value={"nas": {"status": state}, "root": {"status": "ok"}},
            ):
                self.assertEqual(ops.capacity_advisory("warning"), warning)
                self.assertEqual(ops.capacity_advisory("critical"), critical)

    def test_expiration_reboot_future_and_no_smb_reads(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "config").write_text('{"probeMaxAge":180}')
            (root / "boot").write_text("boot")
            with patch.object(ops, "STATE", root), patch.object(
                ops, "CONFIG", root / "config"
            ), patch.object(ops, "BOOT", root / "boot"), patch.object(
                ops.os, "statvfs"
            ) as stat:
                for checked, boot, ok in [
                    (101, "boot", True),
                    (100, "boot", False),
                    (0, "boot", False),
                    (281, "boot", False),
                    (100, "old", False),
                ]:
                    ops.write_json(
                        "capacity.json",
                        {
                            "checked": checked,
                            "boot_id": boot,
                            "nas": {"status": "ok", "accessible": True},
                        },
                    )
                    with patch.object(ops.time, "time", return_value=280):
                        self.assertEqual(ops.nas_ready(), ok)
                stat.assert_not_called()

    def test_blocked_worker_cannot_spawn_another_probe(self):
        with tempfile.TemporaryDirectory() as d, patch.object(
            ops, "STATE", Path(d)
        ), patch.object(ops.os, "statvfs") as stat:
            with ops.lock("probe"):
                ops.probe()
            stat.assert_not_called()

    def test_unavailable_nas_publishes_unknown_and_keeps_root_capacity(self):
        with tempfile.TemporaryDirectory() as d, patch.object(
            ops, "STATE", Path(d)
        ), patch.object(
            ops, "read_json", return_value={"root": {}, "nas": {}}
        ), patch.object(
            ops, "capacity", return_value={"status": "ok"}
        ), patch.object(
            ops.subprocess,
            "check_output",
            side_effect=subprocess.CalledProcessError(1, "findmnt"),
        ):
            ops.probe()
            value = json.loads((Path(d) / "capacity.json").read_text())
            self.assertEqual(value["root"]["status"], "ok")
            self.assertFalse(value["nas"]["accessible"])
            self.assertEqual(value["nas"]["status"], "unknown")


class Recovery(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ready = self.root / "ready"
        self.ready.mkdir()
        self.config = self.root / "config"
        self.config.write_text('{"services":["sonarr","plex"]}')
        for key, value in [
            ("STATE", self.root),
            ("READY", self.ready),
            ("CONFIG", self.config),
        ]:
            context = patch.object(ops, key, value)
            context.start()
            self.addCleanup(context.stop)

    def test_active_nas_does_not_skip_failed_app_and_retries_later(self):
        (self.ready / "sonarr").touch()
        with patch.object(ops, "nas_ready", return_value=True), patch.object(
            ops, "systemctl", return_value=False
        ) as ctl:
            ops.recover()
            ops.recover()
        starts = [
            call.args
            for call in ctl.call_args_list
            if call.args == ("start", "--no-block", "sonarr.service")
        ]
        self.assertEqual(len(starts), 2)
        self.assertFalse(any("plex.service" in c.args for c in ctl.call_args_list))

    def test_unavailable_at_boot_recovers_when_nas_returns(self):
        (self.ready / "sonarr").touch()
        with patch.object(ops, "nas_ready", side_effect=[False, True]), patch.object(
            ops, "systemctl", return_value=False
        ) as ctl:
            ops.recover()
            self.assertFalse(
                any("sonarr.service" in c.args for c in ctl.call_args_list)
            )
            ops.recover()
            self.assertTrue(any("sonarr.service" in c.args for c in ctl.call_args_list))

    def test_holds_persist_and_release_does_not_stop_or_start(self):
        (self.ready / "sonarr").touch()
        with patch.object(ops.os, "geteuid", return_value=0), patch.object(
            ops, "nas_ready", return_value=True
        ), patch.object(ops, "systemctl", return_value=False) as ctl:
            ops.maintenance("hold", "sonarr")
            self.assertEqual((self.root / "holds/sonarr").stat().st_mode & 0o777, 0o600)
            ops.recover()
            self.assertFalse(
                any("sonarr.service" in c.args for c in ctl.call_args_list)
            )
            ops.maintenance("release", "sonarr")
            ops.recover()
            self.assertTrue(any("sonarr.service" in c.args for c in ctl.call_args_list))
            ctl.reset_mock()
            ops.maintenance("hold", "all")
            ops.recover()
            ctl.assert_not_called()
            self.assertTrue(ops.held("plex"))
            with self.assertRaises(ValueError):
                ops.maintenance("hold", "../../elsewhere")


class Advisory(unittest.TestCase):
    def test_endpoints_separate_advisory_status_and_hide_report_contents(self):
        report = {
            "healthy": True,
            "checked": 100,
            "boot_id": "boot",
            "system": "/current",
            "advisories": {
                "applications": {"sonarr": {"status": "warning", "private": "secret"}}
            },
        }
        with patch.object(health, "read_json", return_value=report), patch.object(
            health, "healthy", return_value=True
        ), patch.object(ops, "fresh", return_value=True), patch.object(
            health.os.path, "realpath", return_value="/current"
        ), patch.object(
            ops, "capacity_advisory", return_value=False
        ):
            for path, expected in [
                ("/health", 200),
                ("/advisory/sonarr", 503),
                ("/advisory/capacity-warning", 503),
            ]:
                handler = object.__new__(health.Handler)
                handler.path = path
                handler.wfile = io.BytesIO()
                with patch.object(handler, "send_response") as response, patch.object(
                    handler, "end_headers"
                ):
                    handler.do_GET()
                response.assert_called_once_with(expected)
                self.assertNotIn(b"secret", handler.wfile.getvalue())

    def test_categories_never_expose_raw_warnings(self):
        value = health.warning_categories(
            [
                {"source": "IndexerStatusCheck", "message": "https://secret"},
                {"source": "MovieRemovedCheck", "message": "private-title"},
                {"source": "anything/secret", "message": "private"},
            ]
        )
        self.assertEqual(
            value["counts"], {"indexer": 1, "removed-metadata": 1, "other": 1}
        )
        self.assertNotIn("secret", json.dumps(value))

    def test_advisories_do_not_change_core_health(self):
        with tempfile.TemporaryDirectory() as d, patch.object(
            health, "STATE", Path(d)
        ), patch.object(
            health, "read_json", return_value={"services": {"sonarr": 1}}
        ), patch.object(
            health, "run_check", side_effect=lambda item: (item[0], {"healthy": True})
        ), patch.object(
            health, "arr_advisory", return_value={"status": "warning"}
        ), patch.object(
            ops, "cached_probe", return_value={"nas": {"status": "critical"}}
        ), patch(
            "builtins.print"
        ):
            self.assertEqual(health.check(), 0)
            value = json.loads((Path(d) / "health.json").read_text())
            self.assertTrue(value["healthy"])
            self.assertEqual(
                value["advisories"]["applications"]["sonarr"]["status"], "warning"
            )


class Retention(unittest.TestCase):
    def test_sizes_and_alternatives_use_metadata_only(self):
        row = retention.summarize(
            {
                "ratingKey": "1",
                "addedAt": 86400,
                "viewCount": 0,
                "Media": [{"Part": [{"size": "100"}]}, {"Part": [{"size": "50"}]}],
            },
            {"1": 90000},
            172800,
        )
        self.assertEqual(row["age_days"], 1)
        self.assertTrue(row["watched"])
        self.assertEqual(row["size_bytes"], 150)
        self.assertEqual(row["potential_alternative_bytes"], 100)


if __name__ == "__main__":
    unittest.main()
