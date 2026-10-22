"""Destructive queue transitions are exercised only in temporary directories."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
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
import nixflix_remux as remux


def scene(scene_id, files):
    return {
        "id": scene_id,
        "title": "preserve this title",
        "code": "code",
        "details": "preserve details",
        "director": "director",
        "urls": [],
        "date": "2020-01-01",
        "rating100": 90,
        "organized": True,
        "o_counter": 0,
        "resume_time": 100,
        "play_duration": 200,
        "play_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "studio": {"id": "3"},
        "tags": [{"id": "4"}],
        "performers": [{"id": "5"}],
        "galleries": [],
        "stash_ids": [{"endpoint": "https://example.invalid", "stash_id": "original"}],
        "scene_markers": [],
        "files": files,
    }


class FakeQueue(remux.Queue):
    def __init__(self, config, state, source):
        super().__init__(config, state)
        self.source = source
        self.source_file = {
            "id": "10",
            "path": "data/studio/test.mkv",
            "size": source.stat().st_size,
            "format": "matroska",
            "video_codec": "av1",
            "audio_codec": "aac",
            "fingerprints": [
                {"type": "oshash", "value": "old"},
                {"type": "phash", "value": "123abc"},
            ],
        }
        self.scenes = {"20": scene("20", [self.source_file])}
        self.calls = []
        self.probe_result = {
            "streams": [
                {
                    "codec_name": "av1",
                    "codec_type": "video",
                    "width": 64,
                    "height": 64,
                    "pix_fmt": "yuv420p10le",
                },
                {"codec_name": "aac", "codec_type": "audio", "channels": 2},
            ],
            "format": {"duration": "1.0"},
        }
        self.command_calls = 0

    def api(self, query, variables=None):
        v = variables or {}
        self.calls.append(query)
        if "findFiles(" in query:
            return {"findFiles": {"count": 1, "files": [deepcopy(self.source_file)]}}
        if "findScenes(" in query:
            scenes = [
                s
                for s in self.scenes.values()
                if any(f["path"] == v["path"] for f in s["files"])
            ]
            return {"findScenes": {"count": len(scenes), "scenes": deepcopy(scenes)}}
        if "findScene(" in query:
            return {"findScene": deepcopy(self.scenes.get(v["id"]))}
        if "metadataScan(" in query:
            path = v["input"]["paths"][0]
            file = {
                **self.source_file,
                "id": "11",
                "path": path,
                "format": "mp4",
                "fingerprints": [{"type": "oshash", "value": "new"}],
            }
            file["size"] = self.host_path(path).stat().st_size
            new = scene("21", [file])
            for k in ("stash_ids", "performers", "tags", "galleries", "scene_markers"):
                new[k] = []
            new["play_duration"] = 0
            self.scenes["21"] = new
            return {"metadataScan": "1"}
        if "findJob(" in query:
            return {"findJob": {"status": "FINISHED", "error": None}}
        if "sceneMerge(" in query:
            source = self.scenes.pop(v["source"])
            self.scenes[v["dest"]]["files"].extend(source["files"])
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
        raise AssertionError(query)

    def probe(self, path, job):
        return deepcopy(self.probe_result)

    def command(self, args, job, *, output=False):
        self.command_calls += 1
        source = Path(args[args.index("-i") + 1])
        if output:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            return f"0,v,SHA256={digest}\n1,a,SHA256={digest}\n"
        Path(args[-1]).write_bytes(source.read_bytes())


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / "media"
        self.source = self.media / "studio/test.mkv"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"identical compressed streams")
        os.utime(self.source, (time.time() - 300, time.time() - 300))
        cfg = {
            "mediaRoot": str(self.media),
            "stashRoot": "/data",
            "requireMount": False,
            "reserveBytes": 0,
            "ffmpeg": "ffmpeg",
            "ffprobe": "ffprobe",
        }
        self.queue = FakeQueue(cfg, self.root / "state", self.source)
        self.queue.plan()

    def job(self):
        return json.loads((self.queue.jobs / "10.json").read_text())

    def test_full_lifecycle_preserves_scene_and_hash_then_deletes_source(self):
        before = deepcopy(self.queue.scenes["20"])
        result = self.queue.run()
        self.assertEqual(result["counts"], {"complete": 1})
        self.assertFalse(self.source.exists())
        self.assertTrue(self.source.with_suffix(".mp4").exists())
        after = self.queue.scenes["20"]
        self.assertEqual(len(after["files"]), 1)
        self.assertEqual(after["files"][0]["id"], "11")
        self.assertIn(
            {"type": "phash", "value": "123abc"}, after["files"][0]["fingerprints"]
        )
        for k in before:
            if k != "files":
                self.assertEqual(before[k], after[k], k)
        self.queue.run()
        self.assertEqual(self.queue.command_calls, 3)

    def test_conflict_never_overwrites_or_deletes(self):
        dst = self.source.with_suffix(".mp4")
        dst.write_bytes(b"existing")
        self.queue.run()
        self.assertEqual(dst.read_bytes(), b"existing")
        self.assertTrue(self.source.exists())
        self.assertEqual(self.job()["status"], "skipped")

    def test_subtitles_are_not_silently_discarded(self):
        self.queue.probe_result["streams"].append(
            {"codec_type": "subtitle", "codec_name": "ass"}
        )
        self.queue.run()
        self.assertTrue(self.source.exists())
        self.assertEqual(self.queue.command_calls, 0)

    def test_non_aac_is_skipped(self):
        self.queue.source_file["audio_codec"] = "ac3"
        plan = self.queue.state / "plan.json"
        data = json.loads(plan.read_text())
        data["files"][0]["audio_codec"] = "ac3"
        remux.atomic_json(plan, data)
        self.queue.run()
        self.assertTrue(self.source.exists())
        self.assertEqual(self.queue.command_calls, 0)

    def test_hash_mismatch_keeps_mkv_and_does_not_publish(self):
        with patch.object(
            self.queue, "stream_hashes", side_effect=[["old", "old"], ["new", "new"]]
        ):
            self.queue.run()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.source.with_suffix(".mp4").exists())
        self.assertEqual(self.job()["phase"], "remuxed")

    def test_changed_source_refuses_deletion(self):
        real_save = self.queue.save

        def save(job, **changes):
            real_save(job, **changes)
            if changes.get("phase") == "selected":
                self.source.write_bytes(b"new source written concurrently")

        with patch.object(self.queue, "save", side_effect=save):
            self.queue.run()
        self.assertTrue(self.source.exists())
        self.assertEqual(self.job()["status"], "skipped")

    def test_restart_after_rename_before_journal(self):
        real_publish = remux.publish

        def interrupt(src, dst):
            real_publish(src, dst)
            raise KeyboardInterrupt()

        with patch.object(remux, "publish", side_effect=interrupt), self.assertRaises(
            KeyboardInterrupt
        ):
            self.queue.run()
        self.assertEqual(self.job()["phase"], "verified")
        self.assertTrue(self.source.exists())
        self.assertTrue(self.source.with_suffix(".mp4").exists())
        self.queue.run()
        self.assertEqual(self.job()["status"], "complete")

    def test_restart_after_unlink_before_database_cleanup(self):
        real_api = self.queue.api

        def interrupt(query, variables=None):
            if "destroyFiles(" in query:
                raise KeyboardInterrupt()
            return real_api(query, variables)

        with patch.object(self.queue, "api", side_effect=interrupt), self.assertRaises(
            KeyboardInterrupt
        ):
            self.queue.run()
        self.assertFalse(self.source.exists())
        self.assertEqual(self.job()["phase"], "selected")
        self.queue.run()
        self.assertEqual(len(self.queue.scenes["20"]["files"]), 1)
        self.assertEqual(self.job()["status"], "complete")

    def test_restart_after_merge_before_journal(self):
        real_save = self.queue.save

        def interrupt(job, **changes):
            if changes.get("phase") == "attached":
                raise KeyboardInterrupt()
            real_save(job, **changes)

        with patch.object(self.queue, "save", side_effect=interrupt), self.assertRaises(
            KeyboardInterrupt
        ):
            self.queue.run()
        self.assertEqual(self.job()["phase"], "published")
        self.queue.run()
        self.assertEqual(self.job()["status"], "complete")

    def test_low_capacity_stops_without_starting_remux(self):
        self.queue.cfg["reserveBytes"] = 2**63
        with self.assertRaises(remux.Halt):
            self.queue.run()
        self.assertEqual(self.queue.command_calls, 0)
        self.assertTrue(self.source.exists())

    def test_timeout_stops_entire_queue(self):
        with patch.object(
            self.queue, "command", side_effect=remux.Halt("timeout")
        ), self.assertRaises(remux.Halt):
            self.queue.run()
        self.assertEqual(self.job()["status"], "failed")
        self.assertTrue(self.source.exists())

    def test_second_worker_cannot_start(self):
        with self.queue.lock(), self.assertRaises(remux.Halt):
            self.queue.run()

    def test_orphan_child_keeps_worker_lock(self):
        with self.queue.lock():
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                pass_fds=(self.queue.lock_fd,),
            )
        try:
            with self.assertRaises(remux.Halt):
                self.queue.run()
        finally:
            child.terminate()
            child.wait(timeout=5)
        with self.queue.lock():
            pass

    def test_stash_outage_after_publish_retains_original(self):
        real_api = self.queue.api

        def unavailable(query, variables=None):
            if "metadataScan(" in query:
                raise remux.Halt("Stash unavailable")
            return real_api(query, variables)

        with patch.object(
            self.queue, "api", side_effect=unavailable
        ), self.assertRaises(remux.Halt):
            self.queue.run()
        self.assertTrue(self.source.exists())
        self.assertTrue(self.source.with_suffix(".mp4").exists())
        self.assertEqual(self.queue.scenes["20"]["files"][0]["id"], "10")
        self.queue.run(retry=True)
        self.assertEqual(self.job()["status"], "complete")

    def test_multiple_scenes_referencing_source_are_skipped(self):
        self.queue.scenes["22"] = scene("22", [deepcopy(self.queue.source_file)])
        self.queue.run()
        self.assertTrue(self.source.exists())
        self.assertEqual(self.queue.command_calls, 0)

    def test_published_output_changed_before_deletion_is_retained(self):
        real_save = self.queue.save

        def changed(job, **changes):
            real_save(job, **changes)
            if changes.get("phase") == "selected":
                self.source.with_suffix(".mp4").write_bytes(b"changed target")

        with patch.object(self.queue, "save", side_effect=changed):
            self.queue.run()
        self.assertTrue(self.source.exists())
        self.assertEqual(self.job()["status"], "skipped")

    def test_status_reads_no_media_or_api(self):
        with patch.object(self.queue, "api", side_effect=AssertionError), patch.object(
            self.queue, "host_path", side_effect=AssertionError
        ):
            self.assertEqual(self.queue.status()["counts"], {"pending": 1})

    def test_paths_cannot_escape_media_root(self):
        for p in ("/other/test.mkv", "data/../test.mkv"):
            with self.assertRaises(remux.Skip):
                self.queue.host_path(p)
        (self.media / "escape").symlink_to(self.root)
        with self.assertRaises(remux.Skip):
            self.queue.host_path("data/escape/test.mkv")

    def test_symlink_source_is_not_removed(self):
        real = self.source.with_suffix(".original")
        self.source.rename(real)
        self.source.symlink_to(real)
        self.queue.run()
        self.assertTrue(real.exists())
        self.assertTrue(self.source.is_symlink())

    def test_atomic_publish_never_overwrites(self):
        a, b = self.root / "a", self.root / "b"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        with self.assertRaises(remux.Skip):
            remux.publish(a, b)
        self.assertEqual(b.read_bytes(), b"b")

    def test_verified_metadata_tracks_are_allowed(self):
        original = deepcopy(self.queue.probe_result)
        original["streams"][0]["tags"] = {"TIMECODE": "00:00:00:00"}
        original["chapters"] = [
            {"start_time": "0", "end_time": "1", "tags": {"title": "Chapter 1"}}
        ]
        converted = deepcopy(original)
        converted["streams"][0]["tags"] = {"timecode": "00:00:00:00"}
        converted["streams"].extend(
            [
                {
                    "codec_type": "data",
                    "codec_tag_string": "tmcd",
                    "tags": {"timecode": "00:00:00:00"},
                },
                {"codec_type": "data", "codec_tag_string": "text"},
            ]
        )
        remux.verify_layout(original, converted)

    def test_unexpected_extra_track_is_rejected(self):
        converted = deepcopy(self.queue.probe_result)
        converted["streams"].append(
            {
                "codec_type": "data",
                "codec_tag_string": "tmcd",
                "tags": {"timecode": "00:00:00:00"},
            }
        )
        with self.assertRaises(remux.Skip):
            remux.verify_layout(self.queue.probe_result, converted)

    def test_changed_chapter_is_rejected(self):
        original = deepcopy(self.queue.probe_result)
        original["chapters"] = [
            {"start_time": "0", "end_time": "1", "tags": {"title": "Chapter 1"}}
        ]
        converted = deepcopy(original)
        converted["chapters"][0]["end_time"] = "0.5"
        with self.assertRaises(remux.Skip):
            remux.verify_layout(original, converted)

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required"
    )
    def test_real_av1_aac_remux_and_full_stream_hash_verification(self):
        chapters = self.root / "chapters.txt"
        chapters.write_text(
            ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\ntitle=Chapter 1\n"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=64x64:rate=5",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000",
                "-f",
                "ffmetadata",
                "-i",
                str(chapters),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-map_metadata",
                "2",
                "-map_chapters",
                "2",
                "-metadata:s:v:0",
                "timecode=00:00:00:00",
                "-t",
                "1",
                "-c:v",
                "libaom-av1",
                "-cpu-used",
                "8",
                "-threads",
                "1",
                "-c:a",
                "aac",
                str(self.source),
            ],
            check=True,
            timeout=30,
        )
        os.utime(self.source, (time.time() - 300, time.time() - 300))
        self.queue.source_file["size"] = self.source.stat().st_size
        data = json.loads((self.queue.state / "plan.json").read_text())
        data["files"][0]["size"] = self.source.stat().st_size
        remux.atomic_json(self.queue.state / "plan.json", data)
        self.queue.command = remux.Queue.command.__get__(self.queue)
        self.queue.probe = remux.Queue.probe.__get__(self.queue)
        result = self.queue.run()
        self.assertEqual(result["counts"], {"complete": 1})
        self.assertFalse(self.source.exists())
        probe = self.queue.probe(self.source.with_suffix(".mp4"), {"id": "10"})
        self.assertEqual(probe["streams"][0]["codec_name"], "av1")


if __name__ == "__main__":
    unittest.main()
