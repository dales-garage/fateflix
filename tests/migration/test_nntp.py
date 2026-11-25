import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SECRETS = ROOT / "capabilities/secrets"
sys.path.insert(0, str(SECRETS))
from nntp_credentials import KEYS, validate
import provision


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nntp = load("nntp", ROOT / "capabilities/downloads/nntp.py")
store = load("store", SECRETS / "provision-secrets.py")
POLICY = json.loads((ROOT / "capabilities/downloads/nntp-servers.json").read_text())


class NntpCredentials(unittest.TestCase):
    def values(self):
        return {key: "synthetic-" + key for key in KEYS}

    def test_scoped_manifest_and_staging_guard(self):
        manifest = tomllib.loads((SECRETS / "secretspec-nntp.toml").read_text())
        self.assertEqual(set(manifest["profiles"]), {"nntp"})
        self.assertEqual(set(manifest["profiles"]["nntp"]), set(KEYS))
        self.assertEqual(set(POLICY["credentials"]), set(KEYS))
        with self.assertRaises(ValueError):
            provision.command("provision-nntp", "staging", "pass")
        command = provision.command("provision-nntp", "production", "pass")
        self.assertTrue(command[2].endswith("secretspec-nntp.toml"))
        self.assertIn("nntp", command)

    def test_endpoint_migration_preserves_unrelated_state(self):
        config = {"misc": {"api_key": "synthetic-api"}, "categories": {"books": {}},
            "servers": {"news.vipernews.com": {"retention": "3500", "priority": "2"},
                "news.newsgroupdirect.com@1": {"enable": "1"},
                "unmanaged": {"host": "example.invalid", "enable": "0"}}}
        original = copy.deepcopy(config)
        result = nntp.configure(config, self.values(), POLICY)
        self.assertEqual(config, original)
        self.assertEqual(result["misc"]["api_key"], config["misc"]["api_key"])
        self.assertEqual(result["misc"]["bandwidth_max"], "30000000")
        self.assertEqual(result["misc"]["bandwidth_perc"], "100")
        self.assertEqual(result["categories"]["books"], config["categories"]["books"])
        self.assertEqual(result["categories"]["prowlarr"]["dir"], "prowlarr")
        self.assertEqual(result["servers"]["unmanaged"], dict(config["servers"]["unmanaged"], retention="0"))
        viper = result["servers"]["viper.newsgroupdirect.com"]
        self.assertEqual(viper["password"], self.values()["VIPERNEWS_PASSWORD"])
        self.assertEqual(viper["retention"], "0")
        self.assertEqual(viper["priority"], "2")
        self.assertEqual(viper["connections"], "4")
        self.assertEqual(result["servers"]["farm.newsgroupdirect.com"]["connections"], "6")
        self.assertEqual(result["servers"]["news.newsgroupdirect.com@1"]["enable"], "0")
        for server in POLICY["servers"]:
            actual = result["servers"][server["name"]]
            self.assertEqual(actual["ssl_verify"], "3")
            self.assertEqual(actual["port"], "563")
        self.assertEqual(nntp.configure(result, self.values(), POLICY), result)

    def test_invalid_credentials_leave_input_untouched(self):
        config = {"servers": {"old": {"enable": "1"}}}
        for invalid in ["", "injected\r\nsetting", "bad\x00value"]:
            values = dict(self.values(), NGD_PASSWORD=invalid)
            with self.assertRaises(ValueError):
                nntp.configure(config, values, POLICY)
            self.assertEqual(config, {"servers": {"old": {"enable": "1"}}})
        with self.assertRaises(ValueError):
            validate({})

    def test_private_generation_and_interrupted_rotation(self):
        values = self.values()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "nntp"
            store.install(values, root, keys=KEYS, validator=validate)
            previous = os.readlink(root / "current")
            self.assertTrue(store.valid_generation(root / "current", root, values, keys=KEYS))
            for path in (root / "current").iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            changed = dict(values, NGD_PASSWORD="new-synthetic-value")
            with patch.object(store.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    store.install(changed, root, keys=KEYS, validator=validate)
            self.assertEqual(os.readlink(root / "current"), previous)
            self.assertEqual((root / "current/NGD_PASSWORD").read_text(), values["NGD_PASSWORD"])
            store.install(changed, root, keys=KEYS, validator=validate)
            self.assertEqual((root / "current/NGD_PASSWORD").read_text(), changed["NGD_PASSWORD"])


if __name__ == "__main__":
    unittest.main()
