"""Durable Whisparr intake and verified H.264-to-AV1 Stash replacements."""

import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid
import xml.etree.ElementTree as ET

import nixflix_remux as media

CONFIG = Path("/etc/nixflix/imports.json")
FORMATS = {
    "NixFlix HEVC": r"(?i)\b(?:x[ ._-]?265|h[ ._-]?265|hevc)\b",
    "NixFlix AV1": r"(?i)\b(?:av1|av01)\b",
}


class RetryStashTask(media.Halt):
    """A vanished or terminated task can be safely resubmitted."""


def identifier(value):
    value = str(value)
    media.require(bool(re.fullmatch(r"[1-9][0-9]{0,12}", value)), "invalid import ID")
    return value


def arr(cfg, method, path, value=None):
    key = ET.parse(cfg["whisparrConfig"]).findtext("ApiKey")
    req = urllib.request.Request(
        cfg["whisparrUrl"].rstrip("/") + "/api/v3/" + path,
        data=json.dumps(value).encode() if value is not None else None,
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None


def enqueue(inbox, environ):
    env = {k.lower(): v for k, v in environ.items()}
    event = env.get("whisparr_eventtype", "")
    if event == "Test":
        return
    if event != "Download":
        return
    file_id = identifier(env.get("whisparr_episodefile_id", ""))
    series_id = identifier(env.get("whisparr_series_id", ""))
    # No media paths, credentials, API access, or FFmpeg in the import hook.
    media.atomic_json(
        Path(inbox) / (file_id + ".json"),
        {"file_id": file_id, "series_id": series_id, "created": time.time()},
    )


def reconcile(cfg, call=arr):
    deadline = time.monotonic() + 120
    while True:
        try:
            call(cfg, "GET", "system/status")
            break
        except (OSError, ET.ParseError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)
    formats = call(cfg, "GET", "customformat")
    managed = {}
    for name, regex in FORMATS.items():
        desired = {
            "name": name,
            "includeCustomFormatWhenRenaming": False,
            "specifications": [
                {
                    "name": "Release title",
                    "implementation": "ReleaseTitleSpecification",
                    "negate": False,
                    "required": True,
                    "fields": [{"name": "value", "value": regex}],
                }
            ],
        }
        found = next((f for f in formats if f["name"] == name), None)
        canonical = lambda f: [
            (
                s.get("implementation"),
                s.get("negate"),
                s.get("required"),
                [(v["name"], v.get("value")) for v in s.get("fields", [])],
            )
            for s in f.get("specifications", [])
        ]
        if found is None:
            found = call(cfg, "POST", "customformat", desired)
        elif canonical(found) != canonical(desired) or found.get(
            "includeCustomFormatWhenRenaming"
        ):
            found = call(
                cfg, "PUT", "customformat/" + str(found["id"]), dict(found, **desired)
            )
        managed[found["id"]] = name
    for profile in call(cfg, "GET", "qualityprofile"):
        updated = deepcopy(profile)
        items = updated.setdefault("formatItems", [])
        for fmt, name in managed.items():
            item = next((i for i in items if i["format"] == fmt), None)
            if item is None:
                items.append({"format": fmt, "name": name, "score": 100})
            else:
                item["score"] = 100
        # Keep quality ordering, existing scores, minimum/cutoff scores and
        # upgrade choices. In particular H.264 remains an eligible fallback.
        if updated != profile:
            call(cfg, "PUT", "qualityprofile/" + str(profile["id"]), updated)
    name = "NixFlix Stash imports"
    existing = next(
        (n for n in call(cfg, "GET", "notification") if n["name"] == name), None
    )
    desired = (
        deepcopy(existing)
        if existing
        else deepcopy(
            next(
                n
                for n in call(cfg, "GET", "notification/schema")
                if n["implementation"] == "CustomScript"
            )
        )
    )
    desired.update(
        name=name, onDownload=True, onUpgrade=True, onGrab=False, onRename=False
    )
    for f in desired["fields"]:
        if f["name"] == "path":
            f["value"] = cfg["hook"]
        elif f["name"] == "arguments":
            f["value"] = ""
    if existing is None:
        desired.pop("id", None)
        call(cfg, "POST", "notification", desired)
    elif desired != existing:
        call(cfg, "PUT", "notification/" + str(existing["id"]), desired)


class Imports(media.Queue):
    def save(self, job, **changes):
        job.update(changes, updated=time.time())
        media.atomic_json(self.jobs / (job["key"] + ".json"), job)

    def destination_suffix(self):
        return ".av1.mp4"

    def scenes_for_path(self, path):
        scenes = super().scenes_for_path(path)
        if not scenes:
            alternate = path.lstrip("/") if path.startswith("/") else "/" + path
            scenes = super().scenes_for_path(alternate)
        return scenes

    def virtual_path(self, host_path):
        path, root = PurePosixPath(host_path), PurePosixPath(self.cfg["mediaRoot"])
        media.require(
            path.is_absolute() and ".." not in path.parts and path.is_relative_to(root),
            "import outside media root",
        )
        virtual = str(PurePosixPath(self.cfg["stashRoot"]) / path.relative_to(root))
        media.require(
            not media.candidate_exclusion(virtual),
            "hidden or encoder work file excluded",
        )
        return virtual

    def wait_stash(self, task):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            job = self.api(
                "query($id:ID!){findJob(input:{id:$id}){status error}}", {"id": task}
            )["findJob"]
            if job is None:
                raise RetryStashTask("Stash task disappeared; retry its verified stage")
            if job["status"] == "FINISHED":
                if job["error"]:
                    raise RetryStashTask("Stash task failed; inspect Stash job logs")
                return
            if job["error"] or job["status"] in {"FAILED", "CANCELLED", "STOPPED"}:
                raise RetryStashTask("Stash task did not finish")
            time.sleep(2)
        raise media.Halt("Stash task exceeded ten minutes")

    def scan(self, job, path, label):
        key = label + "_task"
        if not job.get(key):
            options = {
                "paths": [path],
                "rescan": True,
                "scanGeneratePhashes": label == "source_scan",
            }
            for name in (
                "Covers",
                "Previews",
                "ImagePreviews",
                "Sprites",
                "ImagePhashes",
                "Thumbnails",
                "ClipPreviews",
            ):
                options["scanGenerate" + name] = False
            task = self.api(
                "mutation($input:ScanMetadataInput!){metadataScan(input:$input)}",
                {"input": options},
            )["metadataScan"]
            self.save(job, **{key: task})
        if not job.get(label + "_done"):
            try:
                self.wait_stash(job[key])
            except RetryStashTask:
                # An idempotent path scan can safely be resubmitted next time.
                self.save(job, **{key: None})
                raise
            self.save(job, **{label + "_done": True})

    def identify(self, job):
        if job.get("identify_done"):
            return
        if not job.get("identify_task"):
            cfg = self.api("{configuration{general{stashBoxes{endpoint}}}}")
            endpoints = [
                x["endpoint"]
                for x in cfg["configuration"]["general"]["stashBoxes"]
                if urlsplit(x["endpoint"]).hostname == "stashdb.org"
            ]
            if not endpoints:
                raise media.Halt("StashDB provider is not configured")
            options = {
                "skipMultipleMatches": True,
                "skipSingleNamePerformers": True,
                "setOrganized": False,
                "setCoverImage": False,
                "fieldOptions": [
                    {
                        "field": k,
                        "strategy": "MERGE",
                        "createMissing": k in {"performers", "studio", "tags"},
                    }
                    for k in (
                        "title",
                        "details",
                        "date",
                        "director",
                        "urls",
                        "performers",
                        "studio",
                        "tags",
                    )
                ],
            }
            task = self.api(
                "mutation($input:IdentifyMetadataInput!){metadataIdentify(input:$input)}",
                {
                    "input": {
                        "sceneIDs": [job["scene_id"]],
                        "sources": [
                            {"source": {"stash_box_endpoint": e}} for e in endpoints
                        ],
                        "options": options,
                    }
                },
            )["metadataIdentify"]
            self.save(job, identify_task=task)
        try:
            self.wait_stash(job["identify_task"])
        except RetryStashTask:
            self.save(job, identify_task=None)
            raise
        self.save(job, identify_done=True)

    @contextmanager
    def intake_lock(self):
        with (self.state / "intake.lock").open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise media.Halt("another intake worker owns the lock") from e
            yield

    def ingest(self):
        with self.intake_lock():
            return self.collect()

    def collect(self):
        inbox = Path(self.cfg["inbox"])
        handled = {
            str(j["whisparr_file_id"]): j
            for p in self.jobs.glob("*.json")
            if (j := json.loads(p.read_text())).get("whisparr_file_id")
        }
        for path in sorted(inbox.glob("*.json")):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as f:
                    s = os.fstat(f.fileno())
                    media.require(
                        stat.S_ISREG(s.st_mode) and s.st_size <= 4096,
                        "invalid import event",
                    )
                    event = json.loads(f.read(4097))
                file_id, series_id = identifier(event["file_id"]), identifier(
                    event["series_id"]
                )
                media.require(
                    path.name == file_id + ".json", "import event identity mismatch"
                )
                media.require(
                    isinstance(event["created"], (int, float))
                    and 0 < event["created"] <= time.time() + 60,
                    "invalid event timestamp",
                )
            except (OSError, ValueError, KeyError, media.Skip):
                quarantine = self.state / "quarantine"
                quarantine.mkdir(mode=0o700, exist_ok=True)
                media.atomic_json(
                    quarantine / (uuid.uuid4().hex + ".json"),
                    {"reason": "invalid import event", "created": time.time()},
                )
                path.unlink()
                continue
            key = "whisparr-" + file_id
            known = handled.get(file_id)
            if known is None:
                known = {
                    "key": key,
                    "origin": "whisparr",
                    "whisparr_file_id": file_id,
                    "series_id": int(series_id),
                    "created": event["created"],
                    "phase": "queued",
                    "status": "ingesting",
                }
                self.save(known)
            if known["status"] == "ingesting":
                if known.get("next_attempt", 0) > time.time():
                    continue
                try:
                    info = arr(self.cfg, "GET", "episodefile/" + file_id)
                    media.require(
                        info["seriesId"] == int(series_id),
                        "Whisparr event series changed",
                    )
                    virtual = self.virtual_path(info["path"])
                    self.scan(known, virtual, "source_scan")
                    scenes = self.scenes_for_path(virtual)
                    media.require(
                        len(scenes) == 1, "import scene association requires review"
                    )
                    matches = [
                        f
                        for f in scenes[0]["files"]
                        if str(PurePosixPath("/") / f["path"]) == virtual
                    ]
                    media.require(
                        len(matches) == 1, "import file association requires review"
                    )
                    source = matches[0]
                    self.save(
                        known,
                        path=source["path"],
                        id=source["id"],
                        scene_id=scenes[0]["id"],
                    )
                    self.identify(known)
                    if source["video_codec"] == "h264":
                        self.save(
                            known,
                            status="queued",
                            phase="queued",
                            identify_done=False,
                            identify_task=None,
                            next_attempt=max(time.time(), event["created"] + 120),
                        )
                    else:
                        self.save(
                            known,
                            status="complete",
                            phase="complete",
                            action="scan-identify-only",
                            completed=time.time(),
                        )
                except media.Skip as e:
                    self.save(known, status="skipped", error=str(e))
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        self.save(
                            known,
                            status="skipped",
                            error="Whisparr import record no longer exists",
                        )
                    else:
                        self.save(
                            known,
                            status="ingesting",
                            error_type=type(e).__name__,
                            next_attempt=time.time() + 300,
                        )
                        break
                except Exception as e:
                    self.save(
                        known,
                        status="ingesting",
                        error_type=type(e).__name__,
                        next_attempt=time.time() + 300,
                    )
                    break
            media.require(
                path.lstat().st_ino == s.st_ino, "import event changed while collecting"
            )
            path.unlink()
        return self.status()

    def refresh_inventory(self):
        record_path = self.state / "backfill-scan.json"
        record = json.loads(record_path.read_text()) if record_path.exists() else {}
        if not record.get("task") or record.get("finished"):
            options = {"paths": [self.cfg["stashRoot"]], "rescan": False}
            for name in (
                "Covers",
                "Previews",
                "ImagePreviews",
                "Sprites",
                "Phashes",
                "ImagePhashes",
                "Thumbnails",
                "ClipPreviews",
            ):
                options["scanGenerate" + name] = False
            task = self.api(
                "mutation($input:ScanMetadataInput!){metadataScan(input:$input)}",
                {"input": options},
            )["metadataScan"]
            record = {"task": task, "started": time.time()}
            media.atomic_json(record_path, record)
        try:
            self.wait_stash(record["task"])
        except RetryStashTask:
            media.atomic_json(record_path, dict(record, task=None))
            raise
        media.atomic_json(record_path, dict(record, finished=time.time()))

    def backfill(self, refresh=False):
        with self.lock():
            if refresh:
                self.refresh_inventory()
            managed = {}
            for series in arr(self.cfg, "GET", "series"):
                for f in arr(
                    self.cfg, "GET", "episodefile?seriesId=" + str(series["id"])
                ):
                    try:
                        managed[self.virtual_path(f["path"])] = {
                            "series_id": f["seriesId"],
                            "whisparr_file_id": str(f["id"]),
                        }
                    except media.Skip:
                        continue
            known = [json.loads(p.read_text()) for p in self.jobs.glob("*.json")]
            page, added, size = 1, 0, 0
            while True:
                data = self.api(
                    'query($page:Int!){findFiles(file_filter:{video_file_filter:{video_codec:{value:"h264",modifier:EQUALS}}},filter:{page:$page,per_page:200,sort:"id",direction:ASC}){count files{... on VideoFile{id path size audio_codec}}}}',
                    {"page": page},
                )["findFiles"]
                for f in data["files"]:
                    virtual = str(PurePosixPath("/") / f["path"])
                    if not PurePosixPath(virtual).is_relative_to(
                        PurePosixPath(self.cfg["stashRoot"])
                    ) or media.candidate_exclusion(virtual):
                        continue
                    key = "stash-" + identifier(f["id"])
                    whisparr = managed.get(virtual, {})
                    if (self.jobs / (key + ".json")).exists() or any(
                        j.get("id") == f["id"]
                        or (
                            whisparr.get("whisparr_file_id")
                            and j.get("whisparr_file_id")
                            == whisparr["whisparr_file_id"]
                        )
                        for j in known
                    ):
                        continue
                    self.save(
                        {
                            **f,
                            **whisparr,
                            "key": key,
                            "origin": "backfill",
                            "created": time.time(),
                        },
                        phase="queued",
                        status="queued",
                        next_attempt=0,
                    )
                    added += 1
                    size += f["size"]
                if page * 200 >= data["count"]:
                    break
                page += 1
            return {"added": added, "source_bytes": size}

    def prepare(self, job):
        if job["phase"] == "queued":
            if job["origin"] == "whisparr":
                info = arr(self.cfg, "GET", "episodefile/" + job["whisparr_file_id"])
                media.require(
                    info["seriesId"] == job["series_id"],
                    "Whisparr import series changed",
                )
                path = self.virtual_path(info["path"])
                self.save(job, path=path)
            media.require(
                not media.candidate_exclusion(job["path"]),
                "hidden or work file excluded",
            )
            self.scan(job, job["path"], "source_scan")
            scenes = self.scenes_for_path(job["path"])
            media.require(len(scenes) == 1, "source scene association needs review")
            scene = scenes[0]
            matches = [
                f
                for f in scene["files"]
                if str(PurePosixPath("/") / f["path"])
                == str(PurePosixPath("/") / job["path"])
            ]
            media.require(len(matches) == 1, "source file association needs review")
            source = matches[0]
            self.save(
                job,
                id=source["id"],
                path=source["path"],
                size=source["size"],
                before_scene=scene,
                scene_id=scene["id"],
                phase="pending",
            )
        src = self.host_path(job["path"])
        if job["phase"] == "pending":
            probe = self.probe(src, job)
            video = [s for s in probe["streams"] if s["codec_type"] == "video"]
            media.require(len(video) == 1, "multiple video streams require review")
            if video[0]["codec_name"] != "h264":
                self.identify(job)
                self.save(
                    job,
                    phase="complete",
                    status="complete",
                    action="scan-identify-only",
                    completed=time.time(),
                )
                return
            media.require(
                job["before_scene"]["files"][0]["id"] == job["id"],
                "source is not scene primary; review alternatives",
            )
            media.require(
                all(s["codec_type"] in {"video", "audio"} for s in probe["streams"]),
                "subtitle or attachment requires review; source retained",
            )
            media.require(
                any(s["codec_type"] == "audio" for s in probe["streams"]),
                "no audio track; review required",
            )
            media.require(
                video[0].get("color_transfer") not in {"smpte2084", "arib-std-b67"},
                "HDR source requires review; source retained",
            )
            sig = media.signature(src)
            media.require(
                sig["st_size"] == job["size"], "source size changed after scan"
            )
            if time.time() - sig["st_mtime_ns"] / 1e9 < 120:
                raise media.Halt("source is still settling")
            if self.cfg.get("requireMount", True) and not os.path.ismount(
                self.cfg["mount"]
            ):
                raise media.Halt("media mount is unavailable")
            capacity = os.statvfs(src.parent)
            if (
                capacity.f_bavail * capacity.f_frsize
                < self.cfg["reserveBytes"] + 2 * sig["st_size"]
            ):
                raise media.Halt("insufficient free space above reserve")
            media.require(
                not os.path.lexists(src.with_suffix(self.destination_suffix())),
                "AV1 destination already exists",
            )
            partial = src.parent / (
                ".nixflix-remux-" + job["id"] + "-" + uuid.uuid4().hex + ".part"
            )
            self.save(
                job,
                source=sig,
                probe=probe,
                partial=str(partial),
                phase="encoding",
                published_after=time.time(),
            )
        partial = Path(job["partial"])
        media.require(
            partial.parent == src.parent
            and partial.name.startswith(".nixflix-remux-" + job["id"] + "-"),
            "invalid temporary output path",
        )
        if job["phase"] == "encoding":
            media.require(
                job.get("encoding_attempts", 0) < 3,
                "encoding interrupted three times; source retained for review",
            )
            self.save(job, encoding_attempts=job.get("encoding_attempts", 0) + 1)
            media.require(
                media.signature(src) == job["source"], "source changed before encoding"
            )
            if os.path.lexists(partial):
                media.signature(partial)
                partial.unlink()
            args = [
                self.cfg["ffmpeg"],
                "-hide_banner",
                "-v",
                "warning",
                "-xerror",
                "-err_detect",
                "explode",
                "-nostdin",
                "-n",
                "-i",
                str(src),
                "-map",
                "0",
                "-map_metadata",
                "0",
                "-map_chapters",
                "0",
                "-c:v",
                "libsvtav1",
                "-crf",
                str(self.cfg["crf"]),
                "-preset",
                str(self.cfg["preset"]),
                "-pix_fmt",
                "yuv420p10le",
                "-threads",
                "2",
                "-svtav1-params",
                "lp=2",
                "-fps_mode",
                "passthrough",
                "-c:a",
                "copy",
            ]
            video = next(
                s for s in job["probe"]["streams"] if s["codec_type"] == "video"
            )
            for field, option in (
                ("color_range", "-color_range"),
                ("color_space", "-colorspace"),
                ("color_transfer", "-color_trc"),
                ("color_primaries", "-color_primaries"),
            ):
                if video.get(field) and video[field] not in {"unknown", "unspecified"}:
                    args += [option, video[field]]
            audio = [s for s in job["probe"]["streams"] if s["codec_type"] == "audio"]
            for i, stream in enumerate(audio):
                if stream["codec_name"] != "aac":
                    args += [
                        "-c:a:" + str(i),
                        "aac",
                        "-b:a:" + str(i),
                        "384k" if stream.get("channels", 2) > 2 else "192k",
                    ]
            args += [
                "-movflags",
                "+faststart",
                "-fs",
                str(2 * job["source"]["st_size"]),
                "-f",
                "mp4",
                str(partial),
            ]
            self.command(args, job)
            self.save(job, phase="encoded")
        if job["phase"] == "encoded":
            media.require(
                job.get("validation_attempts", 0) < 3,
                "validation interrupted three times; source retained for review",
            )
            self.save(job, validation_attempts=job.get("validation_attempts", 0) + 1)
            self.validate(job, src, partial)

    def validate(self, job, src, partial):
        media.require(
            media.signature(src) == job["source"], "source changed during encoding"
        )
        original, converted = job["probe"], self.probe(partial, job)
        expected = deepcopy(original)
        for stream in expected["streams"]:
            if stream["codec_type"] == "video":
                stream.update(codec_name="av1", profile="Main", pix_fmt="yuv420p10le")
            elif stream["codec_name"] != "aac":
                stream.update(codec_name="aac", profile="LC")
        media.verify_layout(expected, converted)
        old_video = next(s for s in original["streams"] if s["codec_type"] == "video")
        new_video = next(s for s in converted["streams"] if s["codec_type"] == "video")
        for key in (
            "sample_aspect_ratio",
            "color_range",
            "color_space",
            "color_transfer",
            "color_primaries",
        ):
            if old_video.get(key) and old_video[key] not in {"unknown", "unspecified"}:
                media.require(
                    new_video.get(key) == old_video[key],
                    "video presentation metadata changed: " + key,
                )
        media.require(
            abs(
                float(original["format"]["duration"])
                - float(converted["format"]["duration"])
            )
            < 0.25,
            "converted duration differs",
        )
        frames = json.loads(
            self.command(
                [
                    self.cfg["ffprobe"],
                    "-v",
                    "error",
                    "-count_frames",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=nb_read_frames",
                    "-of",
                    "json",
                    str(src),
                ],
                job,
                output=True,
            )
        )["streams"][0]["nb_read_frames"]
        decoded = self.command(
            [
                self.cfg["ffmpeg"],
                "-hide_banner",
                "-v",
                "error",
                "-xerror",
                "-err_detect",
                "explode",
                "-nostdin",
                "-threads",
                "2",
                "-i",
                str(partial),
                "-map",
                "0:v:0",
                "-map",
                "0:a",
                "-fps_mode",
                "passthrough",
                "-progress",
                "pipe:1",
                "-f",
                "null",
                "-",
            ],
            job,
            output=True,
        )
        counts = re.findall(r"^frame=([0-9]+)$", decoded, re.M)
        media.require(
            bool(counts) and int(counts[-1]) == int(frames) > 0,
            "decoded frame count differs",
        )
        old, new = self.stream_hashes(src, job), self.stream_hashes(partial, job)
        audio = [s for s in original["streams"] if s["codec_type"] == "audio"]
        media.require(
            len(old) == len(new) == 1 + len(audio), "stream hash count differs"
        )
        for i, stream in enumerate(audio, 1):
            if stream["codec_name"] == "aac":
                media.require(old[i] == new[i], "copied audio packet hashes differ")
        media.require(
            media.signature(src) == job["source"], "source changed during validation"
        )
        s = src.stat()
        os.chown(partial, s.st_uid, s.st_gid)
        os.chmod(partial, stat.S_IMODE(s.st_mode))
        with partial.open("rb") as f:
            os.fsync(f.fileno())
        self.save(
            job,
            phase="verified",
            target=media.signature(partial),
            hashes=new,
            validated_frames=int(frames),
        )

    def finalize(self, job):
        target = str(PurePosixPath(job["path"]).with_suffix(self.destination_suffix()))
        self.scan(job, target, "final_scan")
        if job.get("series_id") and not job.get("whisparr_rescan_done"):
            if not job.get("whisparr_rescan_id"):
                cmd = arr(
                    self.cfg,
                    "POST",
                    "command",
                    {"name": "RescanSeries", "seriesId": job["series_id"]},
                )
                self.save(job, whisparr_rescan_id=cmd["id"])
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                cmd = arr(self.cfg, "GET", "command/" + str(job["whisparr_rescan_id"]))
                if cmd["status"].lower() == "completed":
                    files = arr(
                        self.cfg, "GET", "episodefile?seriesId=" + str(job["series_id"])
                    )
                    target_path = str(PurePosixPath("/") / target)
                    matches = []
                    for f in files:
                        try:
                            if (
                                str(PurePosixPath("/") / self.virtual_path(f["path"]))
                                == target_path
                            ):
                                matches.append(f)
                        except media.Skip:
                            continue
                    if len(matches) != 1:
                        self.save(job, whisparr_rescan_id=None)
                        raise media.Halt(
                            "Whisparr has not registered the AV1 replacement"
                        )
                    self.save(job, whisparr_rescan_done=True)
                    break
                if cmd["status"].lower() in {"failed", "aborted", "cancelled"}:
                    self.save(job, whisparr_rescan_id=None)
                    raise media.Halt("Whisparr rescan failed")
                time.sleep(2)
            if not job.get("whisparr_rescan_done"):
                raise media.Halt("Whisparr rescan exceeded ten minutes")
        self.identify(job)

    def process(self, job):
        if job["phase"] in {"queued", "pending", "encoding", "encoded"}:
            self.prepare(job)
        if job["phase"] != "complete":
            super().process(job)

    def run_imports(self):
        with self.lock():
            jobs = [json.loads(p.read_text()) for p in self.jobs.glob("*.json")]
            for job in sorted(
                jobs, key=lambda j: (j["origin"] != "whisparr", j["created"])
            ):
                if (
                    job["status"] not in {"queued", "waiting", "running"}
                    or job.get("next_attempt", 0) > time.time()
                ):
                    continue
                try:
                    self.save(job, status="running", error=None, error_type=None)
                    self.process(job)
                except media.Skip as e:
                    self.save(job, status="skipped", error=str(e))
                except Exception as e:
                    self.save(
                        job,
                        status="waiting",
                        error=str(e),
                        error_type=type(e).__name__,
                        next_attempt=time.time() + 300,
                    )
                    # A blocked API/NAS or timeout must not start more jobs.
                    break
                print(
                    json.dumps(
                        {
                            "job": job["key"],
                            "phase": job["phase"],
                            "status": job["status"],
                        }
                    ),
                    flush=True,
                )
                # One bounded media job per unit invocation; intake runs
                # separately so scans/identification do not wait for encoding.
                break
        return self.status()

    def status(self):
        counts = {}
        for p in self.jobs.glob("*.json"):
            s = json.loads(p.read_text())["status"]
            counts[s] = counts.get(s, 0) + 1
        return {"counts": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument(
        "action",
        choices=["enqueue", "ingest", "reconcile", "backfill", "run", "status"],
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="refresh Stash's directory inventory before a backfill",
    )
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    if args.action == "enqueue":
        enqueue(cfg["inbox"], os.environ)
        return
    os.umask(0o077)
    if args.action == "reconcile":
        reconcile(cfg)
        return
    queue = Imports(cfg, cfg["state"])
    if args.action == "backfill":
        print(json.dumps(queue.backfill(refresh=args.scan)), flush=True)
        return
    result = {
        "run": queue.run_imports,
        "status": queue.status,
        "ingest": queue.ingest,
    }[args.action]()
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
