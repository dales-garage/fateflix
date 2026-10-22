# Playback reliability and recovery

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

## Promotion and acceptance

Promote sequential reviewed changes: (1) credential and evaluation-fixture fixes,
(2) storage advisories/recovery and Notifiarr retries, (3) reversible GPU settings
and playback diagnostics. Each PR must pass the existing affected-check planner
and production build when its derivation changes. Keep documents with their
corresponding implementation. Observe each runtime rollout for 30 minutes during
low usage before promoting the next one. Do not combine fault injection with
production acceptance.

Playback diagnostics and the read-only hypervisor preflight arrive in the dependent playback PR.

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
