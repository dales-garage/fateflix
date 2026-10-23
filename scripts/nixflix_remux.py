"""Finite, journalled AV1/AAC MKV-to-MP4 queue for the Stash library.

Only `run` removes source files. Discovery uses Stash metadata; every candidate
is probed and its complete compressed streams are hashed before replacement.
"""

import argparse
from collections import Counter
from contextlib import contextmanager
import ctypes
from datetime import datetime
import errno
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

SCENE = """id title code details director urls date rating100 organized o_counter
resume_time play_duration play_count created_at studio{id} tags{id}
performers{id} galleries{id} stash_ids{endpoint stash_id} scene_markers{id}
files{id path size format video_codec audio_codec fingerprints{type value}}"""
ACTIVITY = {"resume_time", "play_duration", "play_count", "o_counter", "files"}


class Skip(Exception):
    """Candidate needs review; keep its source."""


class Halt(Exception):
    """Stop the whole queue; an external dependency needs attention."""


def atomic_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        try:
            os.chmod(temporary, 0o600)
            json.dump(value, f)
            f.flush()
            os.fsync(f.fileno())
            os.replace(temporary, path)
            fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)


def signature(path):
    s = Path(path).lstat()
    if not stat.S_ISREG(s.st_mode):
        raise Skip("not a regular file")
    return {k: getattr(s, k) for k in ("st_dev", "st_ino", "st_size", "st_mtime_ns")}


def require(condition, message):
    if not condition:
        raise Skip(message)


def candidate_exclusion(api_path):
    path = PurePosixPath(api_path)
    if any(part.startswith(".") for part in path.parts):
        return "hidden file or directory excluded"
    if ".av1-work-" in path.name.lower():
        return "temporary AV1 work file excluded"
    return None


def tags(value):
    return {k.lower(): v for k, v in value.get("tags", {}).items()}


def timecode(value):
    # MP4 can omit frame-number padding below 10 fps. Keep the drop-frame
    # separator while comparing numeric components.
    return tuple(int(p) if p.isdecimal() else p for p in re.split("([:;])", value))


def verify_layout(original, converted):
    old_streams = original["streams"]
    new_streams = [
        s for s in converted["streams"] if s["codec_type"] in {"video", "audio"}
    ]
    require(len(old_streams) == len(new_streams), "audio/video stream count changed")
    timecodes = {
        timecode(tags(s)["timecode"]) for s in old_streams if tags(s).get("timecode")
    }
    chapters, new_chapters = original.get("chapters", []), converted.get("chapters", [])
    require(len(chapters) == len(new_chapters), "chapter count changed")
    for old, new in zip(chapters, new_chapters):
        require(
            all(
                abs(float(old[k]) - float(new[k])) < 0.01
                for k in ("start_time", "end_time")
            ),
            "chapter timing changed",
        )
        require(
            all(tags(new).get(k) == v for k, v in tags(old).items()),
            "chapter metadata changed",
        )
    for old, new in zip(old_streams, new_streams):
        for key in (
            "codec_name",
            "codec_type",
            "profile",
            "pix_fmt",
            "width",
            "height",
            "sample_rate",
            "channels",
            "channel_layout",
        ):
            require(old.get(key) == new.get(key), "stream property changed: " + key)
        if tags(old).get("timecode"):
            require(
                timecode(tags(new).get("timecode", ""))
                == timecode(tags(old)["timecode"]),
                "timecode changed",
            )
    for stream in converted["streams"]:
        if stream["codec_type"] in {"video", "audio"}:
            continue
        # The MP4 muxer can represent existing metadata as an extra track.
        # Accept only independently checked timecode/chapter representations;
        # original media tracks must still all match and pass packet hashes.
        require(
            stream["codec_type"] == "data"
            and (
                (
                    stream.get("codec_tag_string") == "tmcd"
                    and timecode(tags(stream).get("timecode", "")) in timecodes
                )
                or (stream.get("codec_tag_string") == "text" and bool(chapters))
            ),
            "unexpected MP4 track",
        )


def publish(source, destination):
    # Linux RENAME_NOREPLACE: never overwrite a file created during verification.
    libc = ctypes.CDLL(None, use_errno=True)
    ret = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if ret:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise Skip("MP4 destination already exists")
        raise OSError(error, os.strerror(error))


class Queue:
    def __init__(self, config, state):
        self.cfg = config
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.jobs = self.state / "jobs"
        self.jobs.mkdir(exist_ok=True, mode=0o700)
        self.lock_fd = None

    @contextmanager
    def lock(self):
        with (self.state / "worker.lock").open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Halt(
                    "another worker (or its child) still owns the lock"
                ) from error
            self.lock_fd = f.fileno()
            try:
                yield
            finally:
                self.lock_fd = None

    def api(self, query, variables=None):
        headers = {"Content-Type": "application/json"}
        if self.cfg.get("apiKeyFile"):
            headers["ApiKey"] = Path(self.cfg["apiKeyFile"]).read_text().strip()
        request = urllib.request.Request(
            self.cfg["url"].rstrip("/") + "/graphql",
            data=json.dumps({"query": query, "variables": variables or {}}).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        if result.get("errors"):
            raise Halt("Stash rejected a request; see the private job journal")
        return result["data"]

    def host_path(self, api_path):
        path = PurePosixPath(api_path)
        prefix = PurePosixPath(self.cfg.get("stashRoot", "/data"))
        if not path.is_absolute():
            path = PurePosixPath("/") / path
        require(".." not in path.parts, "parent traversal in Stash path")
        try:
            relative = path.relative_to(prefix)
        except ValueError as error:
            raise Skip("file is outside the configured Stash root") from error
        root = Path(self.cfg["mediaRoot"]).resolve(strict=True)
        result = root / relative
        require(
            result.parent.resolve(strict=True).is_relative_to(root),
            "symlink escapes media root",
        )
        return result

    def save(self, job, **changes):
        job.update(changes, updated=time.time())
        atomic_json(self.jobs / (job["id"] + ".json"), job)

    def plan(self):
        with self.lock():
            require(
                not (self.state / "plan.json").exists(), "a finite plan already exists"
            )
            files = []
            page = 1
            while True:
                result = self.api(
                    """query($page:Int!){findFiles(file_filter:{video_file_filter:{
                    video_codec:{value:"av1",modifier:EQUALS},
                    format:{value:"matroska",modifier:EQUALS}}},
                    filter:{page:$page,per_page:200,sort:"id",direction:ASC}){
                    count files{... on VideoFile{id path size audio_codec}}}}""",
                    {"page": page},
                )["findFiles"]
                batch = result["files"]
                files.extend(
                    f
                    for f in batch
                    if f
                    and f["path"].lower().endswith(".mkv")
                    and not candidate_exclusion(f["path"])
                )
                if page * 200 >= result["count"]:
                    break
                page += 1
            # Filter paths lexically here: no NAS probes during discovery.
            root = PurePosixPath(self.cfg.get("stashRoot", "/data"))
            files = [
                f
                for f in files
                if (PurePosixPath("/") / f["path"]).is_relative_to(root)
            ]
            plan = {"version": 1, "created": time.time(), "files": files}
            atomic_json(self.state / "plan.json", plan)
            return {"candidates": len(files), "bytes": sum(f["size"] for f in files)}

    def command(self, args, job, *, output=False):
        # Children inherit the lock. A kernel-blocked orphan prevents a second
        # worker even if its Python parent is terminated. No automatic retries.
        options = {"pass_fds": (self.lock_fd,) if self.lock_fd is not None else ()}
        with (self.jobs / (job["id"] + ".log")).open("ab") as log:
            try:
                result = subprocess.run(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE if output else log,
                    stderr=log,
                    timeout=self.cfg.get("commandTimeout", 3600),
                    **options,
                )
            except subprocess.TimeoutExpired as error:
                raise Halt(
                    "media command timed out; stop before processing another file"
                ) from error
        if result.returncode:
            raise Skip("media command failed; private job log contains details")
        return result.stdout.decode() if output else None

    def probe(self, path, job):
        return json.loads(
            self.command(
                [
                    self.cfg["ffprobe"],
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_chapters",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ],
                job,
                output=True,
            )
        )

    def stream_hashes(self, path, job):
        return self.command(
            [
                self.cfg["ffmpeg"],
                "-hide_banner",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-map",
                "0:v",
                "-map",
                "0:a",
                "-c",
                "copy",
                "-f",
                "streamhash",
                "-hash",
                "sha256",
                "-",
            ],
            job,
            output=True,
        ).splitlines()

    def scene(self, scene_id):
        return self.api(
            "query($id:ID!){findScene(id:$id){" + SCENE + "}}", {"id": scene_id}
        )["findScene"]

    def scenes_for_path(self, path):
        result = self.api(
            "query($path:String!){findScenes(scene_filter:{path:{value:$path,modifier:EQUALS}},"
            "filter:{per_page:10}){count scenes{" + SCENE + "}}}",
            {"path": path},
        )["findScenes"]
        require(result["count"] <= 10, "file has too many scene associations")
        return result["scenes"]

    def process(self, job):
        exclusion = candidate_exclusion(job["path"])
        if exclusion:
            raise Skip(exclusion)
        src = self.host_path(job["path"])
        dst = src.with_suffix(".mp4")
        mp4_path = str(PurePosixPath(job["path"]).with_suffix(".mp4"))
        if job["phase"] == "pending":
            require(not os.path.lexists(dst), "MP4 destination already exists")
            require(job["audio_codec"] == "aac", "non-AAC audio requires review")
            scenes = self.scenes_for_path(job["path"])
            require(len(scenes) == 1, "source must belong to exactly one scene")
            scene = scenes[0]
            require(
                scene["files"][0]["id"] == job["id"],
                "source is not the scene primary file",
            )
            sig = signature(src)
            require(
                sig["st_size"] == job["size"], "source size changed since discovery"
            )
            require(
                time.time() - sig["st_mtime_ns"] / 1e9 >= 120,
                "source was recently modified",
            )
            if self.cfg.get("requireMount", True) and not os.path.ismount(
                self.cfg.get("mount", "/data")
            ):
                raise Halt("media mount is unavailable")
            v = os.statvfs(src.parent)
            if (
                v.f_bavail * v.f_frsize
                < self.cfg.get("reserveBytes", 500 * 1024**3) + 2 * sig["st_size"]
            ):
                raise Halt("insufficient free space above the configured reserve")
            probe = self.probe(src, job)
            streams = probe["streams"]
            require(
                sum(s["codec_type"] == "video" for s in streams) == 1,
                "expected one video stream",
            )
            require(
                all(
                    (s["codec_type"], s["codec_name"])
                    in {("video", "av1"), ("audio", "aac")}
                    for s in streams
                ),
                "subtitle, attachment, data, or incompatible codec requires review",
            )
            require(
                any(s["codec_type"] == "audio" for s in streams), "no AAC audio stream"
            )
            partial = src.parent / (
                ".nixflix-remux-" + job["id"] + "-" + uuid.uuid4().hex + ".part"
            )
            self.save(
                job,
                phase="remuxing",
                source=sig,
                probe=probe,
                scene_id=scene["id"],
                before_scene=scene,
                partial=str(partial),
                published_after=time.time(),
            )

        partial = Path(job["partial"])
        require(
            partial.parent == src.parent
            and partial.name.startswith(".nixflix-remux-" + job["id"] + "-"),
            "invalid partial path in journal",
        )
        if job["phase"] == "remuxing":
            require(signature(src) == job["source"], "source changed before remux")
            require(not os.path.lexists(dst), "MP4 destination already exists")
            # Only this journal's unfinished temporary output may be discarded.
            if os.path.lexists(partial):
                signature(partial)
                partial.unlink()
            self.command(
                [
                    self.cfg["ffmpeg"],
                    "-hide_banner",
                    "-v",
                    "warning",
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
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    "-f",
                    "mp4",
                    str(partial),
                ],
                job,
            )
            self.save(job, phase="remuxed")

        if job["phase"] == "remuxed":
            require(
                signature(src) == job["source"], "source changed before verification"
            )
            original, converted = self.probe(src, job), self.probe(partial, job)
            verify_layout(original, converted)
            require(
                abs(
                    float(original["format"]["duration"])
                    - float(converted["format"]["duration"])
                )
                < 0.25,
                "duration changed",
            )
            old_hashes, new_hashes = self.stream_hashes(src, job), self.stream_hashes(
                partial, job
            )
            require(
                len(old_hashes) == len(original["streams"])
                and old_hashes == new_hashes,
                "complete compressed stream hashes differ",
            )
            require(
                signature(src) == job["source"], "source changed during verification"
            )
            source_stat = src.stat()
            os.chown(partial, source_stat.st_uid, source_stat.st_gid)
            os.chmod(partial, stat.S_IMODE(source_stat.st_mode))
            with partial.open("rb") as f:
                os.fsync(f.fileno())
            self.save(
                job, phase="verified", target=signature(partial), hashes=old_hashes
            )

        if job["phase"] == "verified":
            if os.path.lexists(dst):
                # Recover a crash between the no-replace rename and journalling.
                require(
                    not os.path.lexists(partial) and signature(dst) == job["target"],
                    "MP4 destination conflict",
                )
            else:
                require(
                    signature(partial) == job["target"],
                    "verified temporary file changed",
                )
                publish(partial, dst)
            self.save(job, phase="published")

        require(
            signature(dst) == job["target"], "verified MP4 changed after publication"
        )
        if job["phase"] == "published":
            if not job.get("scan_id"):
                options = {"paths": [mp4_path], "rescan": False}
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
                r = self.api(
                    "mutation($input:ScanMetadataInput!){metadataScan(input:$input)}",
                    {"input": options},
                )
                self.save(job, scan_id=r["metadataScan"])
            deadline = time.monotonic() + 300
            while True:
                scan = self.api(
                    "query($id:ID!){findJob(input:{id:$id}){status error}}",
                    {"id": job["scan_id"]},
                )["findJob"]
                if scan is None:
                    # Completed jobs can disappear after a Stash restart. Do
                    # not blindly resubmit: require the exact file to exist.
                    require(
                        bool(self.scenes_for_path(mp4_path)),
                        "scan job disappeared before file discovery",
                    )
                    break
                if scan["status"] == "FINISHED":
                    require(not scan["error"], "targeted Stash scan failed")
                    break
                if scan["error"] or scan["status"] in {
                    "FAILED",
                    "CANCELLED",
                    "STOPPED",
                }:
                    raise Halt("targeted Stash scan did not finish")
                if time.monotonic() > deadline:
                    raise Halt("targeted Stash scan exceeded five minutes")
                time.sleep(2)
            scenes = self.scenes_for_path(mp4_path)
            require(len(scenes) == 1, "MP4 must belong to one scene")
            target_scene = scenes[0]
            matches = [f for f in target_scene["files"] if f["path"] == mp4_path]
            require(len(matches) == 1, "scanned MP4 not found")
            target_file = matches[0]
            require(
                target_file["format"] == "mp4"
                and target_file["video_codec"] == "av1"
                and target_file["size"] == job["target"]["st_size"],
                "Stash metadata does not match the verified MP4",
            )
            if target_scene["id"] != job["scene_id"]:
                require(
                    len(target_scene["files"]) == 1,
                    "temporary scan scene has other files",
                )
                require(
                    not any(
                        target_scene[k]
                        for k in (
                            "stash_ids",
                            "performers",
                            "tags",
                            "galleries",
                            "scene_markers",
                            "play_count",
                            "play_duration",
                            "o_counter",
                        )
                    ),
                    "temporary scan scene has metadata or activity requiring review",
                )
                require(
                    datetime.fromisoformat(target_scene["created_at"]).timestamp()
                    >= job["published_after"] - 5,
                    "MP4 belongs to a pre-existing scene",
                )
                current = self.scene(job["scene_id"])
                self.save(job, merge_before=current, target_id=target_file["id"])
                self.api(
                    "mutation($source:ID!,$dest:ID!){sceneMerge(input:{source:[$source],destination:$dest,values:{id:$dest},play_history:false,o_history:false}){id}}",
                    {"source": target_scene["id"], "dest": job["scene_id"]},
                )
            self.save(job, phase="attached", target_id=target_file["id"])

        if job["phase"] == "attached":
            current = self.scene(job["scene_id"])
            require(
                current and any(f["id"] == job["target_id"] for f in current["files"]),
                "MP4 is no longer attached",
            )
            if job.get("merge_before"):
                require(
                    all(
                        current[k] == v
                        for k, v in job["merge_before"].items()
                        if k not in ACTIVITY
                    ),
                    "scene metadata changed during association; review before source deletion",
                )
            phashes = [
                p
                for f in job["before_scene"]["files"]
                if f["id"] == job["id"]
                for p in f["fingerprints"]
                if p["type"] == "phash"
            ]
            if phashes:
                self.api(
                    "mutation($input:FileSetFingerprintsInput!){fileSetFingerprints(input:$input)}",
                    {"input": {"id": job["target_id"], "fingerprints": phashes}},
                )
            self.api(
                "mutation($scene:ID!,$file:ID!){sceneUpdate(input:{id:$scene,primary_file_id:$file}){id}}",
                {"scene": job["scene_id"], "file": job["target_id"]},
            )
            self.save(job, phase="selected")

        if job["phase"] == "selected":
            current = self.scene(job["scene_id"])
            require(
                current and current["files"][0]["id"] == job["target_id"],
                "MP4 is no longer the primary file",
            )
            require(
                signature(dst) == job["target"] and bool(job["hashes"]),
                "verified MP4 is unavailable",
            )
            if os.path.lexists(src):
                require(
                    signature(src) == job["source"], "source changed; refuse deletion"
                )
                # Record intent first. A crash after unlink is recoverable using
                # the already verified MP4 and the non-primary original ID.
                self.save(job, deleting_source=True)
                src.unlink()
            else:
                require(
                    job.get("deleting_source"), "source disappeared outside this queue"
                )
            if any(f["id"] == job["id"] for f in current["files"]):
                self.api(
                    "mutation($id:ID!){destroyFiles(ids:[$id])}", {"id": job["id"]}
                )
            self.save(job, phase="complete", status="complete", completed=time.time())

    def run(self, limit=None, retry=False):
        with self.lock():
            if not (self.state / "plan.json").exists():
                return self.status()
            plan = json.loads((self.state / "plan.json").read_text())
            processed = 0
            for candidate in plan["files"]:
                path = self.jobs / (candidate["id"] + ".json")
                job = (
                    json.loads(path.read_text())
                    if path.exists()
                    else {**candidate, "phase": "pending", "status": "pending"}
                )
                if job["status"] == "complete":
                    continue
                # Old discovery plans can contain indexed encoder work files.
                # Classify them locally before resolving paths or retrying a
                # failed job; even --retry must never process these artifacts.
                exclusion = candidate_exclusion(
                    candidate["path"]
                ) or candidate_exclusion(job["path"])
                if exclusion:
                    if job["status"] != "skipped" or job.get("error") != exclusion:
                        previous = job.get("error")
                        self.save(
                            job,
                            status="skipped",
                            error=exclusion,
                            **({"previous_error": previous} if previous else {}),
                        )
                    continue
                if job["status"] in {"skipped", "failed"} and not retry:
                    continue
                self.save(job, status="running", error=None)
                print(
                    json.dumps({"file_id": job["id"], "phase": job["phase"]}),
                    flush=True,
                )
                try:
                    self.process(job)
                except Skip as error:
                    self.save(job, status="skipped", error=str(error))
                except Exception as error:
                    self.save(job, status="failed", error=str(error))
                    raise
                print(
                    json.dumps(
                        {
                            "file_id": job["id"],
                            "status": job["status"],
                            "reason": job.get("error"),
                        }
                    ),
                    flush=True,
                )
                processed += 1
                if limit and processed >= limit:
                    break
            return self.status()

    def status(self):
        path = self.state / "plan.json"
        if not path.exists():
            return {"planned": 0, "counts": {}, "source_bytes_removed": 0}
        plan = json.loads(path.read_text())
        counts, reclaimed, active = Counter(), 0, []
        for f in plan["files"]:
            path = self.jobs / (f["id"] + ".json")
            job = (
                json.loads(path.read_text())
                if path.exists()
                else {**f, "status": "pending"}
            )
            counts[job["status"]] += 1
            if job["status"] == "complete":
                reclaimed += f["size"]
            elif job["status"] in {"running", "failed"}:
                active.append(
                    {k: job.get(k) for k in ("id", "status", "phase", "error")}
                )
        return {
            "planned": len(plan["files"]),
            "counts": dict(counts),
            "source_bytes_removed": reclaimed,
            "active": active,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/nixflix/remux.json")
    parser.add_argument("--state", default="/var/lib/nixflix-remux")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser(
        "plan", help="create a fixed discovery-only plan; never modifies media"
    )
    sub.add_parser("status", help="read local progress without touching the NAS")
    run = sub.add_parser(
        "run", help="resume the plan, deleting verified MKVs after Stash is updated"
    )
    run.add_argument("--limit", type=int)
    run.add_argument(
        "--retry",
        action="store_true",
        help="retry skipped/failed jobs after resolving their cause",
    )
    args = parser.parse_args()
    config = (
        {} if args.action == "status" else json.loads(Path(args.config).read_text())
    )
    queue = Queue(config, args.state)
    try:
        result = (
            queue.run(args.limit, args.retry)
            if args.action == "run"
            else getattr(queue, args.action)()
        )
        print(json.dumps(result), flush=True)
    except (Skip, Halt, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
