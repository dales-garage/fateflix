import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("profiles", ROOT / "reassign-profiles.py")
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)


class ProfileMigration(unittest.TestCase):
    def run_migration(self, fail=False):
        titles = [
            {"id": 1, "path": "/data/a", "monitored": False, "qualityProfileId": 1},
            {"id": 2, "path": "/data/b", "monitored": True, "qualityProfileId": 1},
        ]
        calls = []

        def call(method, path, payload=None):
            calls.append((method, path, payload))
            if (method, path) == ("GET", "qualityprofile"):
                return [{"id": 1, "name": "obsolete"}, {"id": 2, "name": "desired"}]
            if (method, path) == ("GET", "importlist"):
                return []
            if (method, path) == ("GET", "series"):
                return copy.deepcopy(titles)
            if method == "PUT":
                self.assertTrue(path.endswith("?moveFiles=false"))
                if fail and payload["id"] == 2:
                    raise OSError("simulated API failure")
                titles[payload["id"] - 1] = payload
            elif method == "DELETE":
                self.assertTrue(all(t["qualityProfileId"] == 2 for t in titles))

        if fail:
            with self.assertRaises(OSError):
                profiles.migrate(call, "series", "desired")
            self.assertFalse(any(m == "DELETE" for m, _, _ in calls))
        else:
            self.assertEqual(2, profiles.migrate(call, "series", "desired"))
            self.assertEqual([False, True], [t["monitored"] for t in titles])
            self.assertEqual(["/data/a", "/data/b"], [t["path"] for t in titles])
            self.assertEqual(("DELETE", "qualityprofile/1", None), calls[-1])
        self.assertFalse(any("command" in path for _, path, _ in calls))

    def test_import_list_and_collection_references(self):
        lists = [{"id": 10, "qualityProfileId": 1, "enableAutomaticAdd": False}]
        collections = [
            {
                "id": 20,
                "qualityProfileId": 1,
                "monitored": True,
                "rootFolderPath": "/data/movies",
            }
        ]
        deleted = []

        def call(method, path, payload=None):
            if method == "GET":
                return copy.deepcopy(
                    {
                        "qualityprofile": [
                            {"id": 1, "name": "old"},
                            {"id": 2, "name": "desired"},
                        ],
                        "movie": [],
                        "importlist": lists,
                        "collection": collections,
                    }[path]
                )
            if method == "PUT":
                if path.startswith("importlist/"):
                    self.assertFalse(payload["enableAutomaticAdd"])
                    lists[0] = payload
                elif path == "collection/20":
                    self.assertTrue(payload["monitored"])
                    self.assertEqual("/data/movies", payload["rootFolderPath"])
                    collections[0] = payload
                else:
                    self.fail("Unexpected update or bulk refresh")
            if method == "DELETE":
                self.assertEqual(2, lists[0]["qualityProfileId"])
                self.assertEqual(2, collections[0]["qualityProfileId"])
                deleted.append(path)

        profiles.migrate(call, "movie", "desired")
        self.assertEqual(["qualityprofile/1"], deleted)

    def test_reassign_verify_delete(self):
        self.run_migration()

    def test_partial_failure_never_deletes(self):
        self.run_migration(fail=True)


if __name__ == "__main__":
    unittest.main()
