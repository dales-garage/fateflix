import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "download_policy", ROOT / "scripts/download-policy.py"
)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class DownloadPolicyTests(unittest.TestCase):
    def run_policy(self, state, **kwargs):
        writes = []

        def call(method, resource, payload=None):
            if method == "GET":
                return copy.deepcopy(state.get(resource, []))
            writes.append((resource, payload))
            name, record_id = resource.split("/")
            state[name] = [
                copy.deepcopy(payload) if str(item["id"]) == record_id else item
                for item in state[name]
            ]

        policy.reconcile(call, **kwargs)
        return writes

    def test_restored_torrents_disabled_without_deleting_or_changing_usenet(self):
        state = {
            "downloadclient": [
                {"id": 1, "protocol": "torrent", "enable": True},
                {"id": 2, "protocol": "usenet", "enable": True},
            ],
            "indexer": [
                {
                    "id": 3,
                    "protocol": "torrent",
                    "enableRss": True,
                    "enableAutomaticSearch": True,
                    "enableInteractiveSearch": True,
                }
            ],
            "delayprofile": [
                {
                    "id": 4,
                    "enableTorrent": True,
                    "enableUsenet": True,
                    "preferredProtocol": "torrent",
                }
            ],
        }
        writes = self.run_policy(state)
        self.assertEqual(3, len(writes))
        self.assertFalse(state["downloadclient"][0]["enable"])
        self.assertTrue(state["downloadclient"][1]["enable"])
        self.assertFalse(state["indexer"][0]["enableInteractiveSearch"])
        self.assertFalse(state["delayprofile"][0]["enableTorrent"])
        self.assertEqual([], self.run_policy(state))

    def test_torrent_only_delay_profile_moves_to_the_allowed_protocol(self):
        state = {
            "delayprofile": [
                {
                    "id": 1,
                    "enableTorrent": True,
                    "enableUsenet": False,
                    "preferredProtocol": "torrent",
                }
            ]
        }
        self.run_policy(state)
        self.assertEqual(
            state["delayprofile"],
            [
                {
                    "id": 1,
                    "enableTorrent": False,
                    "enableUsenet": True,
                    "preferredProtocol": "usenet",
                }
            ],
        )

    def test_disabling_both_protocols_preserves_a_valid_delay_profile(self):
        state = {
            "downloadclient": [
                {"id": 1, "protocol": "torrent", "enable": True},
                {"id": 2, "protocol": "usenet", "enable": True},
            ],
            "delayprofile": [{"id": 3, "enableTorrent": True, "enableUsenet": True}],
        }
        writes = self.run_policy(state, torrents=False, usenet=False)
        self.assertEqual(
            ["downloadclient/1", "downloadclient/2"], [name for name, _ in writes]
        )
        self.assertEqual(
            state["delayprofile"],
            [{"id": 3, "enableTorrent": True, "enableUsenet": True}],
        )

    def test_permitting_torrents_never_enables_clients(self):
        state = {"downloadclient": [{"id": 1, "protocol": "torrent", "enable": False}]}
        self.assertEqual([], self.run_policy(state, torrents=True))

    def test_prowlarr_disables_all_torrent_providers_by_protocol(self):
        state = {
            "indexer": [
                {
                    "id": 1,
                    "protocol": "torrent",
                    "enable": True,
                    "name": "arbitrary provider",
                },
                {"id": 2, "protocol": "usenet", "enable": True},
            ]
        }
        writes = self.run_policy(state, prowlarr=True)
        self.assertEqual(["indexer/1"], [name for name, _ in writes])
        self.assertTrue(state["indexer"][1]["enable"])
