# Whisparr imports and AV1 conversion

Whisparr prefers releases labelled HEVC/x265/H.265 or AV1/AV01 using two managed
custom formats, each scored 100 in existing profiles. H.264 retains its fallback
eligibility. Quality ordering, unrelated custom-format scores, minimum scores,
upgrade cutoffs and upgrade enablement are preserved. Codec preferences apply
within Whisparr's existing quality ranking and depend on release-title labels.
The unrelated old `Custom_HEVC_x265` format is preserved; it was a language rule
with a zero score rather than an effective codec preference.
The bounded reconciliation waits up to two minutes for Whisparr's API during
startup and retries every five minutes after completion or failure.

## New imports

The managed Custom Script connection uses Whisparr v2's `Download` event and
episode-file/series IDs. It atomically writes a private local event and returns;
it never encodes media or contacts Stash from Whisparr's import process. Test
events are harmless. Other notification connections remain unchanged.

A separate intake service runs each minute. It validates event IDs, asks Whisparr
for the actual imported path, and accepts only files inside `/data/media/porn`.
It scans that exact file in Stash, generates its pHash, and runs Identify with
the existing StashDB provider. HEVC/AV1 imports finish there. H.264 imports enter
the durable conversion queue after a settling period. Intake runs independently
of the encoder, so new scenes do not wait for a long conversion to become visible.
Malformed/symlink events are rejected and recorded privately without blocking
other imports. Events survive an application/API outage and retry after five
minutes; no credentials are exported by the hook.

## Existing directory

The backfill is explicit and finite; no recurring full-directory scan is added:

```sh
sudo nixflix-imports backfill --scan
sudo nixflix-imports status
sudo systemctl start nixflix-import-worker
```

`--scan` asks Stash to refresh the configured directory inventory without
generating covers/previews or transcoding. Discovery then pages existing H.264
file metadata, filters the configured media root and excludes hidden files,
hidden directories and encoder work files. It neither encodes nor deletes during
discovery. Existing queue entries are not overwritten. Whisparr's episode-file
metadata links managed backfill files to their series so their references can
also be refreshed after conversion. Duplicate import events do not create a
second conversion of the same managed file.

## Encoding and validation

One file is converted at a time. New imports have priority over backfill. The
worker can run at any time, capped at **150% CPU** (one and a half vCPUs), two
SVT logical processors, low CPU/I/O priority, 3 GiB RAM, and no swap. Commands
have six-hour bounds and an invocation has an eighteen-hour limit. A worker
blocked in the kernel keeps its lock through inherited child descriptors; do
not force-unmount the share or launch extra workers to bypass it.

Output matches the working scene 1902's format: AV1 Main, 10-bit 4:2:0 and a
fast-start MP4. Balanced settings are SVT-AV1 CRF 28, preset 8; original CRF/preset
were not recoverable from scene 1902's metadata. Dimensions, frame timing and
known colour/aspect metadata are preserved. AAC audio is copied; other audio
tracks are converted to AAC without downmixing or dropping tracks. HDR,
subtitles/attachments, multiple video streams and non-primary scene alternatives
remain for review with their originals intact. Encoding is lossy; validation
does not claim pixel-identical quality or recover missing detail from the input.

Before publication the worker checks all stream/track layout and chapter
metadata, video dimensions/presentation metadata, duration, a complete output
decode and exact decoded video frame count. Copied AAC packets must retain their
SHA-256 hashes. It verifies source identity, syncs the output, preserves ownership
and permissions, and publishes `<original-name>.av1.mp4` without overwriting an
existing file. A 500 GiB free-space reserve plus temporary-output headroom is
required; output size is bounded to prevent an unlimited temporary file.

The original Stash scene is preserved using the same journalled association,
primary-file selection and pHash transfer used by the verified remux queue.
Only after validation and primary-file verification can the old H.264 file be
deleted. Stash's obsolete file reference is then removed. The worker performs
a final targeted scan, refreshes a managed file's Whisparr series reference and
checks that the AV1 path was registered, then runs Identify for the preserved
scene. Identify uses MERGE, skips ambiguous matches and preserves existing covers;
it does not guarantee that StashDB has a matching fingerprint.

## Recovery and operations

```sh
sudo nixflix-imports status
sudo journalctl -u nixflix-import-ingest -u nixflix-import-worker
sudo systemctl stop nixflix-import-worker
sudo systemctl stop nixflix-import-worker.timer
```

Events and jobs are private under `/var/lib/nixflix-imports-inbox` and
`/var/lib/nixflix-imports`. FFmpeg logs are private alongside the jobs. CLI status
and normal worker logs show IDs, phases and counts rather than media titles or
credentials. Review skipped jobs locally; do not reset their state to completed.

Transient failures retry from the recorded stage. A scan/identify task still
running is polled rather than duplicated; a terminated or disappeared task may
be resubmitted. A post-replacement metadata outage retries metadata work without
re-encoding or repeating deletion. Encoding/validation interrupted three times
is retained for review, preventing repeated OOM/timeout loops. Completed or
skipped conversions are not automatically repeated. Do not enable a retry of a
retained source until its failure has been understood.

Global, Whisparr and Stash maintenance holds inhibit new intake/policy/conversion
invocations. Holds do not interrupt an already-running conversion; stop its unit
for immediate maintenance. Nix generations do not restore media or application
databases. This automation is explicitly authorized to delete originals only
after the stated validation; it is not backup or database rollback automation.
