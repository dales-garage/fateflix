import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("usenet_policy", ROOT / "capabilities/downloads/usenet_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def fields(**values):
    return [{"name": key, "value": value} for key, value in values.items()]


class UsenetPolicy(unittest.TestCase):
    def test_quota_update_keeps_provider_key_and_is_idempotent(self):
        records = {"indexer": [{"id": 1, "name": "altHUB", "enable": True,
            "fields": fields(**{"apiKey": "********", "baseSettings.queryLimit": None,
                "baseSettings.grabLimit": None, "baseSettings.limitsUnit": 0})}],
            "downloadclient": [{"id": 2, "name": "sabnzbd", "implementation": "Sabnzbd", "enable": True,
                "fields": fields(host="wrong", port=8080, useSsl=False, category="", apiKey="********")} ]}
        settings = {"Indexers": {1: {"apiKey": "synthetic-provider-key"}},
            "DownloadClients": {2: {"apiKey": "synthetic-sab-key"}}}
        writes = []
        def api(resource, method="GET", data=None):
            if method == "GET":
                return copy.deepcopy(records[resource])
            if resource.endswith("/test"):
                actual = {x["name"]: x["value"] for x in data["fields"]}
                self.assertEqual(actual["host"], "127.0.0.1")
                self.assertEqual(actual["category"], "prowlarr")
                self.assertEqual(actual["apiKey"], "synthetic-sab-key")
                return None
            kind = resource.split("/")[0]
            writes.append(copy.deepcopy(data))
            records[kind] = [copy.deepcopy(data)]
            settings["Indexers" if kind == "indexer" else "DownloadClients"][data["id"]]["apiKey"] = next(x["value"] for x in data["fields"] if x["name"] == "apiKey")
            return data
        config = {"indexers": {"altHUB": {"queries": 4000, "grabs": 500}},
            "sab_client": {"host": "127.0.0.1", "port": 8080, "useSsl": False, "category": "prowlarr"}}
        result = policy.apply(config, api, settings, "synthetic-sab-key")
        self.assertEqual(result, {"indexer_quotas_updated": ["altHUB"], "sab_client_repaired": True})
        self.assertEqual(settings["Indexers"][1]["apiKey"], "synthetic-provider-key")
        self.assertEqual(len(writes), 2)
        result = policy.apply(config, api, settings, "synthetic-sab-key")
        self.assertEqual(result, {"indexer_quotas_updated": [], "sab_client_repaired": False})
        self.assertEqual(len(writes), 2)

    def test_unknown_api_fields_fail_without_mutating_input(self):
        record = {"fields": fields(host="unchanged")}
        with self.assertRaises(ValueError):
            policy.update_fields(record, {"missing": "value"})
        self.assertEqual(record, {"fields": fields(host="unchanged")})


if __name__ == "__main__":
    unittest.main()
