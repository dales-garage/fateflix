"""Import hooks, codec policy and destructive transitions use isolated fixtures."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import nixflix_imports as imports
import nixflix_remux as media
from test_remux import scene


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        self.queue = imports.Imports(
            {"inbox": str(self.inbox), "mediaRoot": "/media", "stashRoot": "/data"},
            self.root / "state",
        )

    def test_test_hook_is_harmless_and_import_event_is_private_and_idempotent(self):
        imports.enqueue(self.inbox, {"Whisparr_EventType": "Test"})
        self.assertEqual(list(self.inbox.iterdir()), [])
        env = {
            "Whisparr_EventType": "Download",
            "Whisparr_EpisodeFile_Id": "12",
            "Whisparr_Series_Id": "3",
            "Whisparr_EpisodeFile_Path": "/private/title.mkv",
        }
        imports.enqueue(self.inbox, env)
        imports.enqueue(self.inbox, env)
        files = list(self.inbox.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            set(json.loads(files[0].read_text())), {"file_id", "series_id", "created"}
        )

    def test_hook_rejects_path_injection_in_ids(self):
        with self.assertRaises(media.Skip):
            imports.enqueue(
                self.inbox,
                {
                    "whisparr_eventtype": "Download",
                    "whisparr_episodefile_id": "../escape",
                    "whisparr_series_id": "3",
                },
            )
        self.assertEqual(list(self.inbox.iterdir()), [])

    def test_malformed_and_symlink_events_do_not_poison_valid_intake(self):
        outside = self.root / "outside"
        outside.write_text("do not change")
        (self.inbox / "1.json").symlink_to(outside)
        (self.inbox / "2.json").write_text("invalid json")
        imports.enqueue(
            self.inbox,
            {
                "whisparr_eventtype": "Download",
                "whisparr_episodefile_id": "3",
                "whisparr_series_id": "4",
            },
        )
        with patch.object(imports, "arr", side_effect=OSError):
            self.queue.ingest()
        self.assertEqual(outside.read_text(), "do not change")
        self.assertEqual(len(list((self.queue.state / "quarantine").glob("*.json"))), 2)
        job = json.loads((self.queue.jobs / "whisparr-3.json").read_text())
        self.assertEqual(job["status"], "ingesting")
        self.assertTrue((self.inbox / "3.json").exists())

    def test_path_boundary_and_work_file_exclusions(self):
        self.assertEqual(
            self.queue.virtual_path("/media/studio/file.mkv"), "/data/studio/file.mkv"
        )
        for path in (
            "/media-other/file.mkv",
            "/media/../file.mkv",
            "/media/studio/.file.av1-work-1.mkv",
        ):
            with self.subTest(path=path), self.assertRaises(media.Skip):
                self.queue.virtual_path(path)

    def test_running_worker_prefers_new_import_and_handles_one_media_job(self):
        self.queue.save(
            {"key": "stash-1", "origin": "backfill", "created": 1},
            status="queued",
            phase="queued",
        )
        self.queue.save(
            {"key": "whisparr-2", "origin": "whisparr", "created": 2},
            status="queued",
            phase="queued",
        )
        processed = []

        def process(job):
            processed.append(job["key"])
            self.queue.save(job, phase="complete", status="complete")

        with patch.object(self.queue, "process", side_effect=process):
            self.queue.run_imports()
        self.assertEqual(processed, ["whisparr-2"])
        self.assertEqual(self.queue.status()["counts"], {"queued": 1, "complete": 1})

    def test_timeout_does_not_resubmit_a_still_running_stash_task(self):
        job = {"key": "stash-1", "source_scan_task": "8"}
        with patch.object(
            self.queue, "wait_stash", side_effect=media.Halt("still running")
        ), patch.object(
            self.queue, "api", side_effect=AssertionError
        ), self.assertRaises(
            media.Halt
        ):
            self.queue.scan(job, "data/file.mkv", "source_scan")
        self.assertEqual(job["source_scan_task"], "8")

    def test_vanished_stash_task_can_be_resubmitted(self):
        job = {"key": "stash-1", "source_scan_task": "8"}
        with patch.object(
            self.queue, "wait_stash", side_effect=imports.RetryStashTask
        ), self.assertRaises(imports.RetryStashTask):
            self.queue.scan(job, "data/file.mkv", "source_scan")
        self.assertIsNone(job["source_scan_task"])

    def test_new_import_does_not_duplicate_an_existing_backfill_job(self):
        self.queue.save(
            {
                "key": "stash-1",
                "origin": "backfill",
                "created": 1,
                "whisparr_file_id": "7",
            },
            status="queued",
            phase="queued",
        )
        imports.enqueue(
            self.inbox,
            {
                "whisparr_eventtype": "Download",
                "whisparr_episodefile_id": "7",
                "whisparr_series_id": "3",
            },
        )
        with patch.object(imports, "arr", side_effect=AssertionError):
            self.queue.ingest()
        self.assertEqual(len(list(self.queue.jobs.glob("*.json"))), 1)
        self.assertEqual(list(self.inbox.iterdir()), [])


class PolicyTests(unittest.TestCase):
    def test_codec_preferences_keep_fallbacks_and_unrelated_policy_and_are_idempotent(
        self,
    ):
        profiles = [
            {
                "id": 1,
                "name": "Existing",
                "upgradeAllowed": False,
                "minFormatScore": 0,
                "cutoffFormatScore": 0,
                "items": [{"quality": {"id": 4}, "allowed": True}],
                "formatItems": [{"format": 9, "name": "Existing score", "score": 5}],
            }
        ]
        original = deepcopy(profiles[0])
        formats = [{"id": 9, "name": "Existing score", "specifications": []}]
        notifications = [{"id": 1, "name": "Notifiarr", "fields": []}]
        writes = []

        def call(cfg, method, path, value=None):
            collection = {
                "qualityprofile": profiles,
                "customformat": formats,
                "notification": notifications,
            }.get(path.split("/")[0])
            if path == "notification/schema":
                return [
                    {
                        "implementation": "CustomScript",
                        "fields": [{"name": "path"}, {"name": "arguments"}],
                    }
                ]
            if method == "GET":
                return deepcopy(collection)
            writes.append((method, path))
            if method == "POST":
                value = dict(value, id=max(x["id"] for x in collection) + 1)
                collection.append(deepcopy(value))
            else:
                collection[:] = [
                    deepcopy(value) if x["id"] == value["id"] else x for x in collection
                ]
            return deepcopy(value)

        imports.reconcile({"hook": "/nix/store/hook"}, call)
        updated = profiles[0]
        self.assertEqual(
            {k: v for k, v in updated.items() if k != "formatItems"},
            {k: v for k, v in original.items() if k != "formatItems"},
        )
        self.assertEqual(updated["formatItems"][0], original["formatItems"][0])
        self.assertEqual([x["score"] for x in updated["formatItems"][1:]], [100, 100])
        self.assertEqual(notifications[0], {"id": 1, "name": "Notifiarr", "fields": []})
        patterns = {
            f["name"]: f["specifications"][0]["fields"][0]["value"]
            for f in formats
            if f["name"].startswith("NixFlix")
        }
        for name, regex in patterns.items():
            self.assertRegex(
                "release.x265.1080p" if name.endswith("HEVC") else "release.AV1.1080p",
                regex,
            )
            self.assertNotRegex("release.H264.1080p", regex)
        count = len(writes)
        imports.reconcile({"hook": "/nix/store/hook"}, call)
        self.assertEqual(len(writes), count)


class StashFixture(imports.Imports):
    def __init__(self, cfg, state, source):
        super().__init__(cfg, state)
        self.source_file = {
            "id": "10",
            "path": "data/studio/test.mkv",
            "size": source.stat().st_size,
            "format": "matroska",
            "video_codec": "h264",
            "audio_codec": "aac",
            "fingerprints": [{"type": "phash", "value": "original-phash"}],
        }
        self.scenes = {"20": scene("20", [self.source_file])}
        self.identified = []

    def api(self, query, variables=None):
        v = variables or {}
        if "findFiles(" in query:
            return {"findFiles": {"count": 1, "files": [deepcopy(self.source_file)]}}
        if "findScenes(" in query:
            matches = [
                s
                for s in self.scenes.values()
                if any(f["path"] == v["path"] for f in s["files"])
            ]
            return {"findScenes": {"count": len(matches), "scenes": deepcopy(matches)}}
        if "findScene(" in query:
            return {"findScene": deepcopy(self.scenes.get(v["id"]))}
        if "metadataScan(" in query:
            path = v["input"]["paths"][0]
            canonical = str(Path("/") / path)
            if not any(
                str(Path("/") / f["path"]) == canonical
                for s in self.scenes.values()
                for f in s["files"]
            ):
                f = dict(
                    self.source_file,
                    id="11",
                    path=path,
                    format="mp4",
                    video_codec="av1",
                    size=self.host_path(path).stat().st_size,
                    fingerprints=[],
                )
                s = scene("21", [f])
                for k in (
                    "stash_ids",
                    "performers",
                    "tags",
                    "galleries",
                    "scene_markers",
                ):
                    s[k] = []
                s["play_duration"] = 0
                self.scenes["21"] = s
            return {"metadataScan": "scan-job"}
        if "findJob(" in query:
            return {"findJob": {"status": "FINISHED", "error": None}}
        if "sceneMerge(" in query:
            s = self.scenes.pop(v["source"])
            self.scenes[v["dest"]]["files"].extend(s["files"])
            return {"sceneMerge": {"id": v["dest"]}}
        if "fileSetFingerprints(" in query:
            for s in self.scenes.values():
                for f in s["files"]:
                    if f["id"] == v["input"]["id"]:
                        f["fingerprints"].extend(v["input"]["fingerprints"])
            return {"fileSetFingerprints": True}
        if "sceneUpdate(" in query:
            s = self.scenes[v["scene"]]
            s["files"].sort(key=lambda f: f["id"] != v["file"])
            return {"sceneUpdate": {"id": s["id"]}}
        if "destroyFiles(" in query:
            for s in self.scenes.values():
                s["files"] = [f for f in s["files"] if f["id"] != v["id"]]
            return {"destroyFiles": True}
        if "configuration" in query:
            return {
                "configuration": {
                    "general": {
                        "stashBoxes": [{"endpoint": "https://stashdb.org/graphql"}]
                    }
                }
            }
        if "metadataIdentify(" in query:
            self.identified.extend(v["input"]["sceneIDs"])
            return {"metadataIdentify": "identify-job"}
        raise AssertionError(query)


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required"
)
class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "media/studio/test.mkv"
        self.source.parent.mkdir(parents=True)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x192:rate=12",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000",
                "-t",
                "0.5",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-c:a",
                "aac",
                str(self.source),
            ],
            check=True,
            capture_output=True,
        )
        os.utime(self.source, (time.time() - 300, time.time() - 300))
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        cfg = {
            "inbox": str(self.inbox),
            "mediaRoot": str(self.root / "media"),
            "stashRoot": "/data",
            "requireMount": False,
            "reserveBytes": 0,
            "ffmpeg": shutil.which("ffmpeg"),
            "ffprobe": shutil.which("ffprobe"),
            "commandTimeout": 30,
            "crf": 28,
            "preset": 12,
        }
        self.queue = StashFixture(cfg, self.root / "state", self.source)
        with patch.object(imports, "arr", return_value=[]):
            self.queue.backfill()

    def job(self):
        return json.loads((self.queue.jobs / "stash-10.json").read_text())

    def test_real_conversion_validation_primary_selection_deletion_and_identification(
        self,
    ):
        before = deepcopy(self.queue.scenes["20"])
        result = self.queue.run_imports()
        self.assertEqual(result["counts"], {"complete": 1}, self.job())
        self.assertFalse(self.source.exists())
        target = self.source.with_suffix(".av1.mp4")
        self.assertTrue(target.exists())
        self.assertEqual(self.job()["validated_frames"], 6)
        probe = self.queue.probe(target, self.job())
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        self.assertEqual(
            (video["codec_name"], video["pix_fmt"]), ("av1", "yuv420p10le")
        )
        after = self.queue.scenes["20"]
        self.assertEqual(len(after["files"]), 1)
        self.assertEqual(after["files"][0]["id"], "11")
        self.assertIn(
            {"type": "phash", "value": "original-phash"},
            after["files"][0]["fingerprints"],
        )
        for k, v in before.items():
            if k != "files":
                self.assertEqual(after[k], v, k)
        self.assertEqual(self.queue.identified, ["20"])

    def test_corrupt_encoded_output_never_publishes_or_deletes_source(self):
        save = self.queue.save

        def corrupt(job, **changes):
            save(job, **changes)
            if changes.get("phase") == "encoded":
                Path(job["partial"]).write_bytes(b"invalid encoded output")

        with patch.object(self.queue, "save", side_effect=corrupt):
            self.queue.run_imports()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.source.with_suffix(".av1.mp4").exists())
        self.assertEqual(self.job()["status"], "skipped")

    def test_resuming_identification_does_not_reencode_or_repeat_deletion(self):
        with patch.object(
            self.queue, "identify", side_effect=media.Halt("unavailable")
        ):
            self.queue.run_imports()
        job = self.job()
        self.assertEqual(job["phase"], "finalizing")
        self.assertEqual(job["status"], "waiting")
        self.assertFalse(self.source.exists())
        self.queue.save(job, next_attempt=0)
        with patch.object(self.queue, "command", side_effect=AssertionError):
            self.queue.run_imports()
        self.assertEqual(self.job()["status"], "complete")

    def test_existing_target_is_preserved_and_original_not_deleted(self):
        target = self.source.with_suffix(".av1.mp4")
        target.write_bytes(b"existing unrelated file")
        self.queue.run_imports()
        self.assertEqual(target.read_bytes(), b"existing unrelated file")
        self.assertTrue(self.source.exists())
        self.assertEqual(self.job()["status"], "skipped")

    def test_h264_mp4_source_gets_a_distinct_validated_destination(self):
        source = self.source.with_suffix(".mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-v",
                "error",
                "-i",
                str(self.source),
                "-c",
                "copy",
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        self.source.unlink()
        self.source = source
        os.utime(source, (time.time() - 300, time.time() - 300))
        self.queue.source_file.update(
            path="data/studio/test.mp4", size=source.stat().st_size, format="mp4"
        )
        self.queue.save(self.job(), path="data/studio/test.mp4")
        self.queue.run_imports()
        self.assertEqual(self.job()["status"], "complete", self.job())
        self.assertFalse(source.exists())
        self.assertTrue(source.with_suffix(".av1.mp4").exists())

    def test_non_aac_audio_is_preserved_as_aac_with_same_channels(self):
        alternate = self.source.with_name("audio.mkv")
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-v",
                "error",
                "-i",
                str(self.source),
                "-c:v",
                "copy",
                "-c:a",
                "ac3",
                str(alternate),
            ],
            check=True,
            capture_output=True,
        )
        os.replace(alternate, self.source)
        os.utime(self.source, (time.time() - 300, time.time() - 300))
        self.queue.source_file.update(
            size=self.source.stat().st_size, audio_codec="ac3"
        )
        self.queue.run_imports()
        self.assertEqual(self.job()["status"], "complete", self.job())
        probe = self.queue.probe(self.source.with_suffix(".av1.mp4"), self.job())
        audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
        self.assertEqual((audio["codec_name"], audio["channels"]), ("aac", 1))

    def test_repeatedly_interrupted_encode_is_bounded_and_retains_original(self):
        original_command = self.queue.command

        def interrupt(args, job, **kwargs):
            if "libsvtav1" in args:
                raise KeyboardInterrupt
            return original_command(args, job, **kwargs)

        with patch.object(
            self.queue, "command", side_effect=interrupt
        ), self.assertRaises(KeyboardInterrupt):
            self.queue.run_imports()
        job = self.job()
        self.assertEqual(job["phase"], "encoding")
        self.queue.save(job, encoding_attempts=3)
        with patch.object(self.queue, "command", side_effect=AssertionError):
            self.queue.run_imports()
        self.assertEqual(self.job()["status"], "skipped")
        self.assertTrue(self.source.exists())

    def test_new_whisparr_import_is_identified_then_converted_and_reindexed(self):
        (self.queue.jobs / "stash-10.json").unlink()
        imports.enqueue(
            self.inbox,
            {
                "Whisparr_EventType": "Download",
                "Whisparr_EpisodeFile_Id": "50",
                "Whisparr_Series_Id": "5",
            },
        )

        def arr(cfg, method, path, value=None):
            if path == "episodefile/50":
                return {"id": 50, "seriesId": 5, "path": str(self.source)}
            if path.startswith("episodefile?"):
                return [{"path": str(self.source.with_suffix(".av1.mp4"))}]
            return {"id": 8} if method == "POST" else {"status": "completed"}

        with patch.object(imports, "arr", side_effect=arr):
            self.queue.ingest()
            path = self.queue.jobs / "whisparr-50.json"
            job = json.loads(path.read_text())
            self.assertEqual(job["status"], "queued")
            self.assertEqual(self.queue.identified, ["20"])
            self.assertTrue(self.source.exists())
            self.assertEqual(list(self.inbox.iterdir()), [])
            self.queue.save(job, next_attempt=0)
            self.queue.run_imports()
        self.assertEqual(json.loads(path.read_text())["status"], "complete")
        self.assertFalse(self.source.exists())
        self.assertEqual(self.queue.identified, ["20", "20"])

    def test_efficient_new_import_only_scans_and_identifies(self):
        (self.queue.jobs / "stash-10.json").unlink()
        self.queue.source_file["video_codec"] = "av1"
        imports.enqueue(
            self.inbox,
            {
                "Whisparr_EventType": "Download",
                "Whisparr_EpisodeFile_Id": "50",
                "Whisparr_Series_Id": "5",
            },
        )
        with patch.object(
            imports,
            "arr",
            return_value={"id": 50, "seriesId": 5, "path": str(self.source)},
        ), patch.object(self.queue, "command", side_effect=AssertionError):
            self.queue.ingest()
        job = json.loads((self.queue.jobs / "whisparr-50.json").read_text())
        self.assertEqual(
            (job["status"], job["action"]), ("complete", "scan-identify-only")
        )
        self.assertTrue(self.source.exists())
        self.assertEqual(self.queue.identified, ["20"])

    def test_whisparr_managed_backfill_is_reindexed_after_replacement(self):
        job = self.job()
        self.queue.save(job, series_id=5, whisparr_file_id="50")
        calls = []

        def arr(cfg, method, path, value=None):
            calls.append((method, path, value))
            if path.startswith("episodefile?"):
                return [{"path": str(self.source.with_suffix(".av1.mp4"))}]
            return {"id": 8} if method == "POST" else {"status": "completed"}

        with patch.object(imports, "arr", side_effect=arr):
            self.queue.run_imports()
        self.assertEqual(self.job()["status"], "complete", self.job())
        self.assertIn(
            ("POST", "command", {"name": "RescanSeries", "seriesId": 5}), calls
        )


if __name__ == "__main__":
    unittest.main()
