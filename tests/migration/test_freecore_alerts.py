"""FreeCORE alerts, recovery and durable delivery use isolated local fixtures."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

SPEC = importlib.util.spec_from_file_location(
    "freecore", Path(__file__).resolve().parents[2] / "scripts/freecore-notifiarr.py"
)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def alert(identifier="disk-1", level="CRITICAL", dismissed=False):
    return {
        "id": identifier,
        "level": level,
        "klass": "SMART",
        "formatted": "Disk needs attention",
        "dismissed": dismissed,
    }


def initial():
    return {"version": 1, "active": {}, "pending": []}


class Alerts(unittest.TestCase):
    def test_unchanged_alert_is_not_repeated_and_escalation_is_forwarded(self):
        first = bridge.reconcile(initial(), [alert(level="WARNING")], "WARNING")
        again = bridge.reconcile(first, [alert(level="WARNING")], "WARNING")
        self.assertEqual(first["pending"], again["pending"])
        escalated = bridge.reconcile(again, [alert()], "WARNING")
        self.assertEqual(len(escalated["pending"]), 2)

    def test_absence_recovers_but_dismissal_does_not_claim_recovery(self):
        state = bridge.reconcile(initial(), [alert()], "WARNING")
        dismissed = bridge.reconcile(state, [alert(dismissed=True)], "WARNING")
        self.assertEqual(len(dismissed["pending"]), 1)
        cleared = bridge.reconcile(dismissed, [], "WARNING")
        self.assertEqual(
            [e["status"] for e in cleared["pending"]], ["firing", "cleared"]
        )
        self.assertFalse(cleared["active"])

    def test_unknown_or_duplicate_records_do_not_clear_existing_alerts(self):
        state = bridge.reconcile(initial(), [alert()], "WARNING")
        before = deepcopy(state)
        for invalid in [[alert(level="UNKNOWN")], [alert(), alert()], {}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                bridge.reconcile(state, invalid, "WARNING")
            self.assertEqual(state, before)

    def test_low_severity_and_previously_dismissed_alerts_are_ignored(self):
        state = bridge.reconcile(
            initial(), [alert(level="NOTICE"), alert("x", dismissed=True)], "WARNING"
        )
        self.assertEqual(state["active"], {})
        self.assertEqual(state["pending"], [])

    def test_delivery_failure_keeps_durable_outbox_and_event_identity(self):
        state = bridge.reconcile(initial(), [alert()], "WARNING")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            bridge.atomic_json(path, state)

            def fail(cfg, event):
                raise OSError("outage")

            with self.assertRaises(OSError):
                bridge.drain({}, state, path, sender=fail)
            self.assertEqual(bridge.private_json(path)["pending"], state["pending"])
            event = state["pending"][0]["event"]
            received = []
            bridge.drain(
                {}, state, path, sender=lambda cfg, e: received.append(e["event"])
            )
            self.assertEqual(received, [event])
            self.assertEqual(bridge.private_json(path)["pending"], [])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_unready_or_unavailable_feed_preserves_active_alerts(self):
        state = bridge.reconcile(initial(), [alert()], "WARNING")
        state["pending"] = []
        for response in [b"false", OSError("offline")]:
            with self.subTest(
                response=response
            ), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "state.json"
                bridge.atomic_json(path, state)
                kwargs = (
                    {"return_value": response}
                    if isinstance(response, bytes)
                    else {"side_effect": response}
                )
                with patch.object(
                    bridge.subprocess, "check_output", **kwargs
                ), patch.object(
                    bridge, "deliver", side_effect=AssertionError
                ), self.assertRaises(
                    (ValueError, OSError)
                ):
                    bridge.run({}, path, 0)
                self.assertEqual(bridge.private_json(path), state)

    def test_successful_poll_persists_before_attempting_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"

            def fail(cfg, event):
                self.assertEqual(
                    bridge.private_json(path)["pending"][0]["event"], event["event"]
                )
                raise OSError("retry later")

            with patch.object(
                bridge.subprocess,
                "check_output",
                side_effect=[b"true", json.dumps([alert()]).encode()],
            ), patch.object(bridge, "deliver", side_effect=fail), self.assertRaises(
                OSError
            ):
                bridge.run({}, path, 0)
            self.assertEqual(len(bridge.private_json(path)["pending"]), 1)

    def test_native_client_serializes_python_scalars_in_a_real_child(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "middlewared"
            package.mkdir()
            (package / "__init__.py").touch()
            (package / "client.py").write_text(
                "import datetime\n"
                "class Client:\n"
                "    def call(self, method):\n"
                "        return True if method == 'system.ready' else [{'datetime': datetime.datetime(2026,10,23)}]\n"
            )
            with patch.dict(os.environ, {"PYTHONPATH": folder}), bridge.lock(
                Path(folder)
            ) as fd:
                self.assertIs(bridge.query("system.ready", 5, fd), True)
                self.assertEqual(
                    bridge.query("alert.list", 5, fd),
                    [{"datetime": "2026-10-23 00:00:00"}],
                )

    def test_http_200_error_is_not_acknowledged(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"result":"error"}'
        opener = MagicMock()
        opener.open.return_value = response
        cfg = {
            "webhook": "https://notifiarr.com/api/v1/notification/passthrough/test",
            "channel": "123456789012345678",
            "hostname": "freecore",
        }
        event = bridge.reconcile(initial(), [alert()], "WARNING")["pending"][0]
        with patch.object(
            bridge.urllib.request, "build_opener", return_value=opener
        ), self.assertRaises(ValueError):
            bridge.deliver(cfg, event)
        response.__enter__.return_value.read.return_value = (
            b'{"details":{"response":"Pass through payload processed."}}'
        )
        with patch.object(bridge.urllib.request, "build_opener", return_value=opener):
            bridge.deliver(cfg, event)

    def test_webhook_and_channel_validation(self):
        cfg = {
            "webhook": "https://notifiarr.com/api/v1/notification/passthrough/test",
            "channel": "123456789012345678",
            "hostname": "freecore",
        }
        bridge.validate_config(cfg)
        for url in [
            "http://notifiarr.com/api/v1/notification/passthrough/test",
            "https://other.test/api/v1/notification/passthrough/test",
            "https://notifiarr.com/api/v1/notification/sonarr/key",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                bridge.validate_config(dict(cfg, webhook=url))

    def test_overlapping_workers_do_not_acquire_the_same_lock(self):
        with tempfile.TemporaryDirectory() as folder, bridge.lock(Path(folder)):
            with self.assertRaises(BlockingIOError), bridge.lock(Path(folder)):
                self.fail("a concurrent cron worker acquired the lock")


if __name__ == "__main__":
    unittest.main()
