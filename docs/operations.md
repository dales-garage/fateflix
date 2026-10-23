# Playback reliability and recovery

For Whisparr codec preferences, new-import scan/identify, and the separately
authorized H.264 backfill/conversion queue, see [AV1 import automation](imports.md).
For FreeCORE disk/pool alerts to the existing Discord errors channel, see
[FreeCORE alert installation](freecore-alerts.md).

Production changes go through reviewed PRs, required CI, and Comin. Keep hosted
Renovate and its existing groups, schedules, and manual merge decisions. If
hosted restrictions become recurrent, assess GitHub Actions before adding update
work to the media VM. Backup automation remains deferred to a separate Xen
Orchestra project. Nix generations restore system software and configuration;
they do not restore application databases or reverse database migrations.
Readarr stays enabled with its existing library pending a separate replacement
assessment. This batch enables no media deletion or database migrations.

## Storage and advisories

SABnzbd has `download_free = 500G`, `complete_free = 500G`, and
`fulldisk_autoresume = 0`. Both limits are 500 GiB. Its built-in protection pauses
download intake when either destination falls below the limit. Other
applications can still write. After deliberately freeing space, check both
folders in SABnzbd's Status page and resume the queue manually. The guard will
pause again if space is still insufficient. See the
[SABnzbd folder documentation](https://sabnzbd.org/wiki/configuration/5.1/folders).
The restored configuration is patched before SABnzbd starts so it receives the
same limits as the declared settings, without replacing providers or queues.

Capacity thresholds in bytes are configurable under `nixflixHost.capacity`:

| Filesystem | Warning below | Critical below |
| --- | --- | --- |
| NAS | 1 TiB | 500 GiB |
| VM root | 20 GiB | 10 GiB |

Equality does not cross a threshold. Root inode pressure warns below 10% free
and becomes critical below 5%, only when meaningful inode totals exist. CIFS
inode counts are excluded because they can be synthetic.

`nixflix-capacity-probe.service` runs once per minute, with a 45-second execution
limit and a five-second stop limit. It records local root capacity before
accessing NAS metadata; it neither enumerates directories nor reads media.
An exclusive local lock remains held by a worker blocked in the kernel, so
later attempts cannot accumulate more NAS workers. Never force-unmount the
share to clear such a worker. Inspect its process state and NAS/network health.
Results expire after `nixflixHost.capacity.probeMaxAge` (180 seconds by default),
and results from a previous boot are unknown. Failed NAS probes publish unknown;
a blocked worker's last results eventually expire. Ordinary health checks and
HTTP endpoints read local state only.

```sh
sudo systemctl start --no-block nixflix-capacity-probe
sudo cat /var/lib/nixflix-gitops/capacity.json
sudo nixflix-health check
curl -i http://127.0.0.1:9199/advisory/capacity-warning
curl -i http://127.0.0.1:9199/advisory/capacity-critical
curl -i http://127.0.0.1:9199/advisory/sonarr
```

All advisory endpoints bind to loopback. Clear results return 200; active
warnings and unknown/stale results return 503. The warning endpoint also fires
for critical capacity; the critical endpoint accepts warning capacity. There
are corresponding endpoints for sonarr-4k, radarr, radarr-4k, lidarr, prowlarr,
readarr, and whisparr. Arr reports contain only counts of indexer,
removed-metadata, download-client, and other warning categories. Raw messages,
provider names, media titles, and URLs are excluded. Existing indexer and
removed-metadata warnings stay visible without changing library entries.
These advisories appear separately in root-only `health.json`. Capacity
pressure and Arr warnings do not change the core `healthy` calculation; NAS
access itself remains a core check. `/health` still checks freshness, the boot
and deployed generation, and build/deployment failures.

Notifiarr's HTTP service checks watch the advisory endpoints through the
existing account integration. During rollout verify that the account has
problem **and recovery** notifications enabled and that actual messages arrive.
Local endpoint success alone does not prove delivery. Test the notification
path using an isolated HTTP fixture registered in the account, without filling
the live NAS or altering its probe state. Notifiarr reconciliation runs every
five minutes after completion, including after failures. Each invocation is
limited to 240 seconds; independent application connections run concurrently.
Unrelated webhooks/providers and the successful-key idempotency markers remain
preserved. Inspect `journalctl -u notifiarr-connections` after an extended outage.
The health checker waits read-only for an in-progress reconciliation to finish,
for at most 245 seconds, rather than treating its temporarily empty exit timestamp
as a failure. It reads state, result and completion timestamp together. Completed
failures, timeouts and a reconciliation that has never completed remain unhealthy.
The existing report stays available while the check waits, subject to its normal
freshness, boot and generation checks. Health checks never start reconciliation.
The health service has an eight-minute overall limit to accommodate the readiness
retry window, this completion wait, and the remaining bounded API checks.

## Recovery and maintenance

Desired-running media services are those listed in `/etc/nixflix/operations.json`
with a marker under `/var/lib/nixflix-migration/ready/`, excluding maintenance
holds. A marker authorizes recovery; it is not proof of health. The recovery timer
checks mount readiness and applications separately every minute. An already
active mount cannot prevent another attempt to start a failed application.
Inactive services are started asynchronously with their NAS/network dependencies.
Unmarked services remain stopped. Download category directories are existing
migration state; NAS readiness no longer creates directories or waits in SMB.

```sh
sudo nixflix-health hold plex
sudo systemctl stop plex
# Work on Plex, then:
sudo nixflix-health release plex
# Global maintenance, including container unit names:
sudo nixflix-health hold all
sudo nixflix-health hold podman-stash
sudo nixflix-health release podman-stash
sudo nixflix-health release all
```

Holds are persistent, root-owned private files under
`/var/lib/nixflix-gitops/holds`. They inhibit recovery and normal service starts,
including across reboot. Creating a hold does not stop an application. Releasing
one does not directly start it; the next recovery pass reconciles it. A plain
`systemctl stop` without a hold is temporary. Service names are systemd names,
for example `podman-stash`, without `.service`. Global and per-service holds
combine; releasing a per-service hold does not override a global hold.

If a service briefly fails during activation, its retry timer can restore it
while Comin still records the deployment as failed. `/health` stays at 503 until
the deployment succeeds. Inspect the failed unit and resolve its cause first.
Run `sudo nixflix-health check`, then compare `sudo comin deployment latest`
with the expected reviewed commit and `readlink /run/current-system`. When the
latest deployment is the intended, already-selected generation, retry it with
`sudo comin deployment submit-latest --operation switch`. Verify the latest
deployment reports `done` and `/health` returns 200. Preserve the failed history;
do not edit health/deployment JSON to make an unsuccessful rollout appear healthy.
This retries configuration activation and does not restore application databases.

Readiness/probe/recovery units reference only `nixflix_ops.py`. The health command
packages its four Python modules explicitly. Unrelated CI and remux script edits
therefore do not change readiness unit paths or restart dependent media services.
The first rollout of this packaging change updates those paths once; validate it
during low usage using the normal runtime rollout procedure.

## Playback diagnostics

GPU enablement sets Stash's pinned host FFmpeg/FFprobe, Intel driver environment,
and device/driver mounts. Disabling it removes those GPU additions and restores
`/usr/bin/ffmpeg`, `/usr/bin/ffprobe`, and software acceleration settings in the
Alpine container. Both transitions preserve unrelated YAML values, file ownership
and private permission bits, using a synced temporary file and atomic replacement.
Malformed YAML and missing enabled FFmpeg tools fail before replacement. The first
original is retained as private `config.before-gpu.yml`; it is not an automatic
rollback of application data. Comments and YAML presentation can be normalized.

```sh
sudo nixflix-health playback
sudo cat /var/lib/nixflix-gitops/playback.json
sudo journalctl -u nixflix-playback --since '-30 minutes'
```

The probe encodes and decodes one second of synthetic H.264 and HEVC inside
Stash. With GPU enabled, those codecs use hardware encoding and decoding. AV1
uses a short software-generated 10-bit fixture followed by hardware decoding:
the production UHD 750 supports AV1 decoding but has no AV1 encoding entrypoint.
See Intel's [media-driver feature matrix](https://github.com/intel/media-driver#decodingencoding-features).
FFmpeg's native AV1 decoder is selected explicitly with VA-API and `p010le`
output. The decoder copies frames to CPU memory before its context is destroyed;
H.264/HEVC retain an explicit hardware-frame download. A missing GPU fails the
AV1 test rather than falling back to libdav1d. The report records AV1's
`decode_transfer = decoder-copyback`. With GPU
disabled, all three codecs use the container's software tools. The report records
each codec's encode/decode mode and the failed stage when applicable.

It uses local cache files and 20-second per-command limits inside the
container plus an outer timeout. It removes its temporary files and never
transcodes library content. Results are separate diagnostics; an unsupported
codec or absent driver does not change core deployment health. It runs initially,
on demand, and after a successful deployment when the kernel, firmware, Intel
drivers, FFmpeg, Stash image, or GPU state fingerprint changes. A successful
unchanged fingerprint and probe version skip the probe within the same boot.
Boot ID and running kernel release are recorded; a new boot always rechecks, so a
pre-reboot success cannot stand in for testing a newly booted kernel. A failed
probe can retry at the next boot or deployment. There is no recurring
background-transcode timer.

On October 23, the AV1 probe intermittently aborted or segfaulted after the host
reboot. The guest still had its expected UHD 750, working firmware and AV1 VA-API
capability. A synthetic-process backtrace showed `hwdownload` calling
`vaSyncSurface` into Intel's AV1 status-report code after the decoder thread had
finished. This matches the decoder/surface lifetime race described in
[Intel media-driver issue 1879](https://github.com/intel/media-driver/issues/1879#issuecomment-5823263516).
Selecting one decoder thread did not eliminate the failure. Decoder-owned
copy-back passed 40 repeated host/container tests, including complete frame
counts, while an absent-device control failed as required. Twenty synthetic
AV1-to-H.264 GPU transcodes also passed. Probe version 3 uses the verified
copy-back path; it does not claim the driver's filter-thread download race is
fixed. No driver reset, passthrough change or reboot is required for this probe
change, and it does not alter Stash's streaming arguments or the conversion queue.

These small synthetic tests do not establish HDR tone mapping, 4K throughput,
client compatibility, or end-to-end AV1 fallback. Keep the existing stable Plex
package, local transcode paths, memory limits and CIFS layout.

## Read-only retention report

```sh
sudo nixflix-health retention
sudo less /var/lib/nixflix-gitops/retention.json
```

This reads paginated movie/episode metadata from Plex and playback history from
Tautulli. The root-only report includes library/title, added age, watched status,
last watch, recorded sizes, version counts, and possible alternative-version
bytes. Sizes come from existing metadata; no filesystem walk or content scan
occurs. Alternative bytes assume retaining the smallest version and are an
estimate requiring manual review: editions, quality, language and user needs can
differ. Watched status combines Plex's account view count with completed watches
in Tautulli; retained history can be incomplete. Neither Maintainerr nor deletion
is enabled. See the [Tautulli API reference](https://github.com/Tautulli/Tautulli/wiki/Tautulli-API-Reference).

## Hypervisor preflight

Run these read-only checks from the XCP-ng host's administrative session, keeping
hypervisor credentials off the media VM. Substitute the VM and host UUIDs after
listing them:

```sh
xe vm-list name-label=nixflix params=uuid,name-label,power-state,resident-on
xe vm-param-get uuid=VM_UUID param-name=other-config param-key=pci
xe vm-param-get uuid=VM_UUID param-name=platform param-key=hvm-pirq
xe host-param-get uuid=HOST_UUID param-name=software-version
uname -r
xl info
lspci -nnk
xl pci-list VM_DOMAIN_ID
```

Confirm the intended Intel device is assigned to this VM and absent from other
VM assignments, `hvm-pirq` is `false`, and record the **running** Xen/kernel/XAPI
versions as well as installed packages. Obtain the domain ID with `xl list`.
On hosts supporting it, `xe pci-list` shows PCI inventory. Review
[XCP-ng PCI passthrough documentation](https://docs.xcp-ng.org/compute/) before
interpreting host-specific results. These commands do not change passthrough,
reload drivers or request a reboot.

## Promotion and acceptance

Promote sequential reviewed changes: (1) credential and evaluation-fixture fixes,
(2) storage advisories/recovery and Notifiarr retries, (3) reversible GPU settings
and playback diagnostics. Each PR must pass the existing affected-check planner
and production build when its derivation changes. Keep documents with their
corresponding implementation. Observe each runtime rollout for 30 minutes during
low usage before promoting the next one. Do not combine fault injection with
production acceptance.

For each rollout record the SHA and Comin status, core and advisory responses,
service journals, free space, and notification problem/recovery delivery. Run the
metadata retention report and inspect it locally. Use the iPhone Safari PWA to
verify direct play, seeking, audio selection, subtitles, and a deliberately
selected AV1 fallback fixture; record the fixture and actual Plex playback mode.
No fixture is assumed safe to delete or transcode permanently. Without those
client and account checks, end-to-end acceptance remains pending.

In isolated tests cover NAS unavailable at boot, recovery after the first failed
app start, persistent holds across reboot, a worker retaining its lock while
blocked, stale/unknown results, and extended notification outage recovery. For
SABnzbd, use a disposable filesystem/test instance to cross the free-space limit,
free space, confirm the queue remains paused, and resume manually. Never fill
production storage or force-unmount the live share for testing.

SecretSpec validates all values before creating a replacement generation. Missing
files and ownership/mode drift create a complete new private generation; unchanged
valid generations remain untouched. Installation writes and syncs every file and
the generation before atomically changing `current`. A failed preparation leaves
the previous generation selected and prints no credential values. An already
incomplete old generation is retained for inspection rather than edited in place.

For a finite batch of AV1 MKVs, see the [verified MP4 remux queue](remux.md).
