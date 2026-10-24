# Verified AV1 remux queue

An iPhone 16 Pro can decode AV1, but Stash's direct MKV stream can stall in its
Safari PWA. Scene 1902 played correctly after its AV1/AAC streams were copied
into a fast-start MP4. This queue applies that operation without re-encoding.
Remuxing changes the container and does not substantially reduce media size.

## Create and run a batch

On the production VM:

```sh
sudo nixflix-remux plan
sudo nixflix-remux status
sudo systemctl start nixflix-remux
sudo journalctl -u nixflix-remux -f
```

`plan` reads Stash's database and records a finite list of AV1 MKV candidates
below `/data/media/porn`. It does not scan media contents or modify media. Review
`/var/lib/nixflix-remux/plan.json` before starting; this file contains private
library paths. An existing plan is never overwritten. Newly downloaded files
are not automatically added to the batch.

Discovery excludes hidden files/directories and AV1 encoder work files whose
names contain `.av1-work-`. Existing plans receive the same exclusion before
any media path resolution, API access, or subprocess starts, including with
`--retry`. Unfinished excluded entries are recorded as skipped; an earlier
failure is retained in the private journal's `previous_error`. Completed entries
are unchanged. No work file or its Stash record is modified or removed.

The service has one worker, low CPU/I/O scheduling priority, a 768 MiB memory
limit, no timer, and no automatic restart. Deployment and reboot do not start
the queue. It retains the configured free-space reserve (500 GiB by default),
plus space for temporary output. No GPU is needed. Stash's media mount stays
read-only; the separate worker writes through the host's existing NAS mount.

## Per-file verification and deletion

The worker requires one AV1 video stream and AAC audio. It skips files with
subtitles, attachments, data streams, incompatible audio, existing MP4 targets,
ambiguous scene associations, or recently changed contents. It copies every
stream, metadata and chapters with FFmpeg `-c copy -movflags +faststart`. It never
silently drops a track to make MP4 accept a file.

Before publishing the MP4, the worker compares stream properties, durations,
and SHA-256 hashes of **all compressed packets in every original audio/video
stream**. MP4 can represent existing timecode and chapter metadata as extra
data tracks; these are accepted only when their corresponding timecodes and
chapter timings/titles are verified. Unexpected extra tracks fail verification.
The worker rechecks
the source identity, preserves permissions, synchronizes the output, and uses a
Linux no-replace rename. A conflicting destination cannot be overwritten.

It then scans only that MP4 in Stash. A new, empty scan scene is combined into
the original scene through Stash's API, retaining the existing scene ID,
metadata and history. The original pHash is copied to the MP4, which is selected
as primary. Only after confirming the MP4 still matches its verified identity
and is primary does the worker unlink the original MKV and remove its obsolete,
non-primary Stash file record. Files whose checks fail retain their MKVs.

Packet hashing proves the compressed streams were preserved; it does not prove
that an already-corrupt input is healthy or that every client can play it.
MP4-incompatible extra tracks are left for review rather than converted or lost.

## Stop, resume and inspect

```sh
sudo systemctl stop nixflix-remux
sudo nixflix-remux status
sudo systemctl start nixflix-remux
```

Root-owned journals and private FFmpeg logs live under
`/var/lib/nixflix-remux/jobs`. Status reads local journals without contacting
Stash or SMB. Progress survives interruption at remuxing, publication, scene
association, primary selection and deletion. A restarted job verifies its
recorded file identities before continuing. Only that job's own unfinished
temporary output may be replaced when restarting an interrupted remux.

Ordinary resume skips previously failed/skipped jobs. After resolving their
cause, stop the service and run `sudo nixflix-remux run --retry`. For an isolated
one-file trial, stop the service and run `sudo nixflix-remux run --limit 1`.
Never run fault-injection tests against the live NAS.

If an older plan stopped on a hidden encoder work file, deploy the exclusion
guard and use the ordinary `systemctl start nixflix-remux` command. It classifies
the old work-file entries locally without retrying other failures. Retain the
original plan and journals; do not delete the temporary files or rewrite a
failed job as completed to clear the queue.

A timeout, unavailable API, or insufficient capacity stops the whole worker.
Inspect the reported failed job before resuming it. Subprocesses inherit the
worker lock: a process blocked in the kernel prevents another worker from
starting even if its parent exits. Do not launch more workers or force-unmount
the share to bypass that lock. No source deletion occurs before verification.

The status field `source_bytes_removed` counts original MKV bytes removed after
successful replacements, not net storage savings. Retain journals for auditing;
they are not application database backups.
