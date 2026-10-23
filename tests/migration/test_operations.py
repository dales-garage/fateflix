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
import nixflix_playback as playback
import nixflix_retention as retention


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


health = load("operations_health", "gitops-health.py")
stash = load("stash_gpu", "configure-stash-gpu.py")


class ReconciliationHealth(unittest.TestCase):
    running = (
        "ActiveState=activating\nResult=success\nExecMainExitTimestampMonotonic=0\n"
    )
    success = (
        "ActiveState=inactive\nResult=success\nExecMainExitTimestampMonotonic=42\n"
    )

    def test_running_reconciliation_waits_for_completed_success(self):
        with patch.object(
            health.subprocess, "check_output", side_effect=[self.running, self.success]
        ) as show, patch.object(health.time, "sleep") as sleep:
            health.completed_oneshot("notifiarr-connections")
            self.assertEqual(show.call_count, 2)
            sleep.assert_called_once()
            self.assertTrue(
                all(
                    call.args[0][:2] == ["systemctl", "show"]
                    for call in show.call_args_list
                )
            )

    def test_running_reconciliation_does_not_hide_a_completed_failure(self):
        failed = self.success.replace("Result=success", "Result=exit-code")
        with patch.object(
            health.subprocess, "check_output", side_effect=[self.running, failed]
        ), patch.object(health.time, "sleep"):
            with self.assertRaises(AssertionError):
                health.completed_oneshot("notifiarr-connections")

    def test_unstarted_reconciliation_is_not_healthy(self):
        unstarted = self.success.replace("=42", "=0")
        with patch.object(health.subprocess, "check_output", return_value=unstarted):
            with self.assertRaises(AssertionError):
                health.completed_oneshot("notifiarr-connections")

    def test_running_reconciliation_has_a_finite_wait(self):
        with patch.object(
            health.subprocess, "check_output", return_value=self.running
        ), patch.object(health.time, "monotonic", side_effect=[0, 1]):
            with self.assertRaises(TimeoutError):
                health.completed_oneshot("notifiarr-connections", wait_seconds=1)

    def test_completed_reconciliation_returns_without_waiting(self):
        with patch.object(
            health.subprocess, "check_output", return_value=self.success
        ) as show, patch.object(health.time, "sleep") as sleep:
            health.completed_oneshot("notifiarr-connections")
            show.assert_called_once()
            sleep.assert_not_called()


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


class GPU(unittest.TestCase):
    def test_enable_disable_enable_preserves_other_values_and_owner(self):
        import yaml

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.yml"
            tool = Path(d) / "ffmpeg"
            tool.touch()
            path.write_text("other: preserved\nffmpeg:\n  unrelated: true\n")
            path.chmod(0o640)
            owner = path.stat().st_uid
            for enabled in [True, False, True]:
                stash.configure(
                    path,
                    str(tool) if enabled else "/usr/bin/ffmpeg",
                    str(tool) if enabled else "/usr/bin/ffprobe",
                    enabled,
                )
                value = yaml.safe_load(path.read_text())
                self.assertEqual(value["ffmpeg"]["hardware_acceleration"], enabled)
                self.assertTrue(value["ffmpeg"]["unrelated"])
                self.assertEqual(value["other"], "preserved")
                self.assertEqual(path.stat().st_uid, owner)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_malformed_missing_tool_and_interruption_preserve_original(self):
        import yaml

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.yml"
            for original in ["invalid: [", "[]", "ffmpeg: false"]:
                path.write_text(original)
                with self.assertRaises((ValueError, yaml.YAMLError)):
                    stash.configure(path, "/absent", "/absent", True)
                self.assertEqual(path.read_text(), original)
            path.write_text("other: preserved")
            with self.assertRaises(ValueError):
                stash.configure(path, "/absent", "/absent", True)
            with patch.object(stash.os, "replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    stash.configure(path, "/usr/bin/ffmpeg", "/usr/bin/ffprobe", False)
            self.assertEqual(path.read_text(), "other: preserved")
            self.assertEqual(list(Path(d).glob(".config-*")), [])

    def test_timeout_and_missing_driver_are_separate_diagnostics(self):
        with tempfile.TemporaryDirectory() as d, patch.object(
            ops, "STATE", Path(d)
        ), patch.object(
            ops,
            "read_json",
            return_value={
                "enabled": True,
                "ffmpeg": "/pinned/ffmpeg",
                "fingerprint": ["test"],
            },
        ), patch.object(
            playback, "command", side_effect=subprocess.TimeoutExpired("ffmpeg", 20)
        ):
            self.assertEqual(playback.playback(), 1)
            value = json.loads((Path(d) / "playback.json").read_text())
            self.assertEqual(len(value["checks"]), 3)
            self.assertTrue(
                all(
                    v["error_type"] == "TimeoutExpired"
                    for v in value["checks"].values()
                )
            )
            self.assertFalse((Path(d) / "health.json").exists())

    def test_unchanged_success_skips_transcoding(self):
        cfg = {"enabled": True, "ffmpeg": "/pinned", "fingerprint": ["same"]}
        with tempfile.TemporaryDirectory() as d, patch.object(
            ops, "STATE", Path(d)
        ), patch.object(
            ops,
            "read_json",
            side_effect=[
                cfg,
                {
                    "healthy": True,
                    "fingerprint": ["same"],
                    "probe_version": playback.PROBE_VERSION,
                    "boot_id": ops.BOOT.read_text().strip(),
                },
            ],
        ), patch.object(
            playback, "command"
        ) as cmd:
            self.assertEqual(playback.playback(True), 0)
            cmd.assert_not_called()

    def test_previous_boot_success_rechecks_the_running_kernel(self):
        cfg = {"enabled": True, "ffmpeg": "/pinned", "fingerprint": ["same"]}
        with tempfile.TemporaryDirectory() as d, patch.object(
            ops, "STATE", Path(d)
        ), patch.object(
            ops,
            "read_json",
            side_effect=[
                cfg,
                {
                    "healthy": True,
                    "fingerprint": ["same"],
                    "probe_version": playback.PROBE_VERSION,
                    "boot_id": "previous-boot",
                },
            ],
        ), patch.object(
            playback, "command"
        ) as cmd:
            self.assertEqual(playback.playback(True), 0)
            self.assertTrue(cmd.called)
            report = json.loads((Path(d) / "playback.json").read_text())
            self.assertEqual(report["boot_id"], ops.BOOT.read_text().strip())
            self.assertEqual(report["running_kernel"], os.uname().release)

    def test_av1_fixture_uses_software_and_requires_native_hardware_decode(self):
        cfg = {"enabled": True, "ffmpeg": "/pinned", "fingerprint": ["test"]}
        with tempfile.TemporaryDirectory() as d, patch.object(
            ops, "STATE", Path(d)
        ), patch.object(ops, "read_json", return_value=cfg), patch.object(
            playback, "command"
        ) as cmd:
            self.assertEqual(playback.playback(), 0)
            commands = [call.args[0] for call in cmd.call_args_list]
            av1 = [
                args for args in commands if any(s.endswith("-av1.mkv") for s in args)
            ]
            encode, decode, cleanup = av1
            self.assertIn("libsvtav1", encode)
            self.assertIn("yuv420p10le", encode)
            self.assertNotIn("av1_vaapi", encode)
            self.assertEqual(decode[decode.index("-c:v") + 1], "av1")
            self.assertLess(decode.index("-c:v"), decode.index("-i"))
            self.assertIn("hwdownload,format=p010le", decode)
            self.assertIn("-hwaccel_output_format", decode)
            self.assertEqual(cleanup[:2], ["rm", "-f"])
            result = json.loads((Path(d) / "playback.json").read_text())
            self.assertEqual(result["checks"]["av1"]["encode_mode"], "software")
            self.assertEqual(result["checks"]["av1"]["decode_mode"], "gpu")

    def test_hardware_decode_failure_is_not_hidden_by_successful_fixture(self):
        cfg = {"enabled": True, "ffmpeg": "/pinned", "fingerprint": ["test"]}

        def command(args, **kwargs):
            if "hwdownload,format=p010le" in args:
                raise subprocess.CalledProcessError(1, args)

        with tempfile.TemporaryDirectory() as d, patch.object(
            ops, "STATE", Path(d)
        ), patch.object(ops, "read_json", return_value=cfg), patch.object(
            playback, "command", side_effect=command
        ):
            self.assertEqual(playback.playback(), 1)
            result = json.loads((Path(d) / "playback.json").read_text())
            self.assertTrue(result["checks"]["h264"]["healthy"])
            self.assertFalse(result["checks"]["av1"]["healthy"])
            self.assertEqual(result["checks"]["av1"]["stage"], "decode")

    def test_legacy_success_rechecks_and_software_mode_does_not_use_gpu(self):
        cfg = {"enabled": False, "ffmpeg": "/pinned", "fingerprint": ["same"]}
        with tempfile.TemporaryDirectory() as d, patch.object(
            ops, "STATE", Path(d)
        ), patch.object(
            ops,
            "read_json",
            side_effect=[cfg, {"healthy": True, "fingerprint": ["same"]}],
        ), patch.object(
            playback, "command"
        ) as cmd:
            self.assertEqual(playback.playback(True), 0)
            commands = [call.args[0] for call in cmd.call_args_list]
            self.assertTrue(any("libsvtav1" in args for args in commands))
            self.assertTrue(all("-hwaccel" not in args for args in commands))
            self.assertTrue(all("-vaapi_device" not in args for args in commands))
            self.assertTrue(
                all(
                    args[0] == "/usr/bin/ffmpeg" for args in commands if args[0] != "rm"
                )
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
