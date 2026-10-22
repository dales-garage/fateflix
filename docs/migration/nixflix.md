# nixflix migration and operations

The personal fork `declarative-dale/nixflix` manages `marty@10.69.0.18`.
`kiriwalawren/nixflix` is an upstream remote. A push never deploys the VM.
The host uses locked NixOS 26.05; the project's original unstable input is retained.

## HTTPS, DNS and remote access

The [Homepage dashboard](../examples/homepage.md) configuration adds a LAN
landing page on port 8082 and `homepage.vm.internal` after host/router deployment.
The [proposed quality policy](quality-policy.md) describes the three codec/size
tiers; it does not apply profile changes or enable automatic Recyclarr sync.

The service manifest `hosts/nixflix/local-services.json` controls the router's
proxy and DNS configuration. Every media service has a LAN-only address under
`vm.internal`, using Caddy's built-in CA and standard HTTPS port 443. For example:

- `https://plex.vm.internal/web/` → `http://10.69.0.18:32400/web/`
- `https://stash.vm.internal/` → `http://10.69.0.18:9999/`
- `https://whisparr.vm.internal/` → `http://10.69.0.18:6969/`
- `https://seeme.vm.internal/` and `https://seerr.vm.internal/` → Seerr

Paths are preserved. Router Unbound resolves these names to `10.69.0.1` from
both the VM and client LAN resolvers (`10.69.0.1` and `10.42.0.1`). Caddy accepts
internal application requests only from `10.69.0.0/24` and `10.42.0.0/24`.
HTTP redirects to HTTPS; no application port is needed in browser URLs.

Install Caddy's **public root certificate** into each client device's trusted
certificate authorities to avoid internal HTTPS trust errors. The router copy is
`/var/db/caddy/data/caddy/pki/authorities/local/root.crt`. Export only that file;
private CA keys stay on the router. The CA and certificate renewal state under
`/var/db/caddy` must be backed up securely. Public certificates for `dalebox.pw`
use Let's Encrypt and do not need this private root installed.

A public copy is available on `.18` at `/var/lib/nixflix-public/caddy-root.crt`.
Its SHA-256 fingerprint is
`75:8D:EA:6E:F2:81:94:ED:F2:06:60:A5:2B:FD:47:70:1F:1D:BF:66:91:5C:0E:6A:1B:72:63:DD:FE:DF:8F:51`.
Copy it with `scp marty@10.69.0.18:/var/lib/nixflix-public/caddy-root.crt .`
and import it as a trusted certificate authority on each client.

Only the `publicServices` allowlist receives public-domain routes. `publicNames`
maps Seerr to its existing `seeme` hostname. The selected public URLs are:

| Service | Public URL | Authentication |
| --- | --- | --- |
| Plex | `https://plex.dalebox.pw/web/` | Plex account |
| Seerr | `https://seeme.dalebox.pw/` | Existing Seerr/Plex login |
| Audiobookshelf | `https://audiobookshelf.dalebox.pw/` | Existing application login |
| Prowlarr | `https://prowlarr.dalebox.pw/` | Router login plus application login |
| Lidarr | `https://lidarr.dalebox.pw/` | Router login plus application login |
| Readarr | `https://readarr.dalebox.pw/` | Router login |
| Mylar3 | `https://mylar3.dalebox.pw/` | Router login |
| Tautulli | `https://tautulli.dalebox.pw/` | Router login; finish application setup |

Stash, Whisparr, Sonarr, Radarr, SABnzbd and both Bazarr instances have no managed
public-domain routes or public DNS records. No public wildcard DNS record is
created. A wildcard *certificate* does not publish wildcard DNS. Jellyfin and
ntfy are not enabled on this VM and have no new routes.

The additional public dashboard username is `nixflix`; retrieve its generated
password securely with `pass show secretspec/nixflix/router_web/BASIC_AUTH_PASSWORD`
on `.18`. It is generated once, encrypted in pass, resolved by SecretSpec, and
only a bcrypt hash is stored in router Caddy's authentication settings. Internal
routes retain application-native authentication. Plex and Audiobookshelf clients
use native application authentication, without an additional router prompt.

Router Caddy listens on static `10.69.0.1:80/443`. OPNsense forwards WAN TCP
80/443 there, preserving its management GUI at `10.42.0.1:443`. Public website
HTTP requests redirect to HTTPS; WAN access to internal-name applications is
rejected. Public DNS uses explicit IPv4 records for the allowed names pointing
to the WAN address, with Cloudflare proxying disabled. The previous Seerr tunnel
DNS record is backed up before changing it; its Ubuntu relay can remain for
rollback until direct WAN ingress has been verified.

Caddy checks the WAN interface IPv4 address every five minutes and updates only
the eight existing allowed DNS records, with TTL 120 seconds. It does not manage
wildcard DNS, IPv6 records or unrelated domains. On initial setup, publish the
explicit records with `public-dns` before relying on this update-only behavior.

Plex additionally has a dedicated **WAN TCP 32400 → 10.69.0.18:32400** forward,
as requested for native Plex remote access and library sharing. This is separate
from the public website's port 443. The ingress app reserves `10.69.0.18` in router
Dnsmasq for the VM adapter `66:f3:5d:b3:84:5a`, preserving its DHCP networking.
Update the manifest's `macAddress` if the hypervisor replaces that adapter.
The VM allows inbound IPv4 TCP 32400; other
application ports remain LAN-restricted and the global IPv6 firewall stays closed.
Plex is configured with manual public port 32400 and advertises
`https://plex.dalebox.pw:443` as an additional custom access URL. Do not replace
Plex's native certificate or server identity. See
[Plex's remote-access guidance](https://support.plex.tv/articles/200289506-remote-access/).

September 7 verification: all 18 internal HTTPS names passed certificate and
application-response checks, including both Seerr aliases. All eight public names
passed public certificate validation; the five guarded dashboards returned 401
without the router credential and 200 with it. A request to the internal Stash
route from the router's non-LAN WAN address returned 403. Plex reported
`mappingState=mapped`, an empty `mappingError`, and public port 32400. These checks
do not constitute an external user's playback test. The independent web probe
service rejected the diagnostic request, so a separate WAN HTTP probe was not
available from this workstation on the LAN.

### Managed router commands

Run these flake apps from the workstation with an authenticated router SSH key,
or append `--control-path PATH` to reuse a temporary authenticated SSH session:

```sh
nix run .#router-https -- plan
nix run .#router-https -- apply
nix run .#router-https -- ingress-plan
nix run .#router-https -- ingress-apply
nix run .#router-dns -- plan
nix run .#router-dns -- apply
nix run .#router-dns -- apply --zone public
nix run .#public-dns -- plan --address WAN_IPV4
nix run .#public-dns -- apply --address WAN_IPV4
```

Validate certificates and authentication using `curl --resolve` before publishing
DNS. `--zone public` changes only router-local DNS; `public-dns` explicitly
changes Cloudflare records. A Git push never changes router or VM configuration.
The router DNS app preserves unrelated overrides and refuses unowned conflicts.

`secretspec-router.toml` declares separate `public_tls` and `router_web` profiles,
without inheriting required application secrets. The Cloudflare token remains in
`secretspec/nixflix/public_tls/CLOUDFLARE_DNS_API_TOKEN` in pass on `.18`; it needs
Zone Read and DNS Edit only for `dalebox.pw`. No account ID is needed. Provisioning
resolves the token through SecretSpec/pass, transfers it only through authenticated
SSH, and persists it in protected router configuration for unattended renewal.
Never print tokens or put them in command arguments, the repo or the Nix store.

The HTTPS app validates OPNsense's model, regenerates both service and Caddyfile
templates, validates with the service's actual certificate storage environment,
and verifies Caddy is running. Native GUI settings contain the public routes;
managed `nixflix-*.conf`/`.global` imports add internal CA routes and static binds.
The ingress app manages native DNAT records for only the three requested ports,
preserving unrelated infrastructure forwards. Configuration backups are root-only
under `/conf/nixflix-https-backups/` and `/conf/nixflix-dns-backups/` on the router.
Cloudflare DNS rollback records are under `/var/lib/nixflix-migration/public-dns-*.json`
on `.18`. Restore only the intended changes when rolling back; VM generations do
not roll back router configuration, DNS records, certificates or application data.

After deploying the repository revision, run on `.18`:

```sh
sudo nix run .#plex-remote -- apply
sudo nix run .#plex-remote -- status
```

## Production cutover, September 7

The user selected the existing September 7 snapshot for production; a newer
snapshot was not taken. `nixosConfigurations.nixflix` now enables production LAN
networking and a writable NAS. `nixflix-staging` retains the isolated configuration
for future preparation. The historical staging observations below apply to that
mode. The internal target/slice names remain `nixflix-staging` in both modes.

Fifteen media instances run natively: Plex, Seerr, Prowlarr, SABnzbd, Lidarr,
HD/4K Sonarr, HD/4K Radarr, HD/4K Bazarr, Tautulli, Audiobookshelf, Readarr and
Whisparr. The second Bazarr uses the native package with a separate systemd unit.
Stash stays on its tested Podman image because the pinned NixOS package is older
than the restored version (0.29.1 versus 0.29.3). Mylar3 also stays on Podman.
Quadlet conversion is a later step for remaining containers. Apprise is prepared
on Podman, disabled until its Discord and Matrix credentials are provided.

Native state lives at `/var/lib/NAME`; Audiobookshelf has `config` and `metadata`
subdirectories and service-specific mappings for its old absolute paths. Original
staged container state remains under `/var/lib/nixflix-containers` for rollback.
`nix run .#migrate-native` copies inactive staged state without deleting it.
`nix run .#restore -- SNAPSHOT SERVICE` now restores these services natively.

All media ports retain their previous numbers at `10.69.0.18`. Firewall rules
allow them from the server LAN `10.69.0.0/24` and the routed client LAN
`10.42.0.0/24`, with the explicit IPv4 TCP 32400 Plex remote-access exception
described above, preserving the global IPv6 firewall boundary.
Apprise is published only on `127.0.0.1:8000`, with no public proxy route. Plex
still sees `/media`, and Stash's media bind remains read-only. Arr, SAB and Bazarr
can write using the shared media group. The NAS readiness service creates the five
managed download category directories only after confirming the real CIFS mount.

The existing Ubuntu Cloudflare tunnel remains running. A temporary
`nixflix-seerr-relay` container on its `arrproxy` network forwards the old
`overseerr:5055` origin to `.18:5055`. It uses Node from the exact already-installed
Overseerr image, no application state, a read-only filesystem and no capabilities.
`nix run .#route-seerr` manages its initial creation from the workstation.
`https://seeme.dalebox.pw` remains the request address, now using direct WAN HTTPS
through router Caddy. Its former tunnel DNS record is backed up. Keep the relay
for rollback until remote access is confirmed, then retire only the relay. Other Ubuntu
infrastructure and tunnel routes remain in place. Retired Notifiarr and Wizarr
origins no longer have running applications and can be removed in Cloudflare.

Twenty source media/retired containers were stopped, with Docker restart policies
set to `no`. Their original policies are recorded on Ubuntu in
`/var/lib/nixflix-migration/final-20260907-cutover/source-containers.json`.
That directory contains the freeze record only, **not a completed new snapshot**.
Never restart source Plex or download writers while the target is active.

To roll back application operation, first stop the target recovery timer and all
media units (stopping the target alone does not stop its Wanted services). Preserve
any new target state and downloads for reconciliation. Stop/remove the Ubuntu
relay, reconnect stopped `overseerr` to `arrproxy` with its original alias, then
restore source restart policies from the saved record and start the selected
source containers. System generation rollback alone does not revert databases.

Pass remains the SecretSpec provider on NixOS; OpenBao is not required for this
single-host setup. Provisioning resolves pass entries and services use persistent,
root-owned credential files, without an unlocked GPG session at boot. Existing
provider settings are preserved in protected application state. Expired indexer
subscriptions require account renewal, separate from host migration.

Run `sudo nix run .#verify-production -- --output
/var/lib/nixflix-migration/verification-production.json` on `.18` to check all
17 active media interfaces, private credentials, NAS write probes and Plex Pass.
The write probes create and immediately remove empty files in download categories;
they do not move or rename media. Run this again after reboot. The isolation test
now rejects production mode and includes the added native services.

### Cutover verification

Production passed test activation, switch, and an unattended reboot. All 17 media
services returned their expected HTTP responses afterward; the public Seerr status
endpoint also returned 200. SSH/sudo, the Xen agent, GPU render device, writable
CIFS mount and service-user category write probes passed. The target had 71 GiB
free on root and approximately 11 GiB memory available after startup. This is an
idle/startup observation, not a multi-stream capacity test.

All four Arr libraries and Lidarr retained their previously recorded titles,
paths, monitored flags and history. Native conversions also preserved these counts:

| Service | Preserved state |
| --- | --- |
| Bazarr HD | 195 shows, 5,682 episodes, 352 movies, 1,960 history rows |
| Bazarr 4K | 70 shows, 1,388 episodes, 105 movies, 107 history rows |
| Tautulli | 1,860 playback history rows |
| Audiobookshelf | 1 user, 3 libraries, 24 library items |
| Readarr | 2 authors, 153 books, 48 history rows |
| Whisparr | 31 series, 3,205 history rows |

Plex returned five authenticated libraries and its account confirmed an active
lifetime Plex Pass. A short forced H.264 transcode from NAS media returned a valid
media segment; Plex reported hardware acceleration requested and an Intel encoder.
The test session was stopped without sending watched-progress updates. Its report
is `verification-plex-transcode.json`; HDR tone mapping and multi-stream load were
not exercised. All seven Prowlarr application tests passed after correcting
the copied Whisparr key. Dormant Arr indexers were also rewritten from the old
Docker hostname to local Prowlarr. SAB was idle with an empty queue after startup;
TLS authentication succeeded with the preserved Eweka and NGD Super credentials.

NZB.su was moved to `https://api.nzb.life` following the
[official retirement notice](https://nzb.su/?lang=de), and its indexer test passed.
DOGnzb, DrunkenSlug and altHUB also passed connection tests. NZBPlanet reported
incorrect credentials, and Tabula Rasa returned HTTP 429; avoid repeated tests
while rate-limited and review those accounts. Five other configured NNTP endpoints
did not authenticate in the standalone TLS probe; review their account/endpoint
settings if they are still intended for use. No download payloads or bulk searches
were submitted by these checks.

Verification reports are protected files on `.18` under
`/var/lib/nixflix-migration/verification-production*.json`. The exact deployed
revision is `/var/lib/nixflix-deploy/deployed`, also pinned by `/etc/nixos/flake.nix`.
Repository operations on the workstation and target use jj; the target checkout was updated
to the personal fork's migration bookmark. Discord/Matrix delivery remains disabled
pending the two pass entries described below. Final client playback and HDR tone
mapping checks remain useful before declaring every playback scenario validated.

## Repository workflow

```sh
nix develop
jj status
jj new migration/nixflix
# Edit and check; jj snapshots new files automatically.
just check
jj commit -m 'Describe the resulting change'
jj bookmark set migration/nixflix -r @-
jj git push --remote origin --bookmark migration/nixflix
nix run .#deploy -- build migration/nixflix
nix run .#deploy -- test migration/nixflix
nix run .#deploy -- switch migration/nixflix
```

The deployment command resolves one Git commit with jj and builds that exact
revision from the personal fork on the target. `test` must succeed before `switch`.
A new SSH connection checks sudo, hostname, and the Xen guest agent. The deployed
commit is recorded in `/var/lib/nixflix-deploy/deployed`. `/etc/nixos/flake.nix`
points to that exact revision. Edit this repository for further system changes.

For upstream changes, run `jj git fetch --remote upstream`, inspect
`jj log -r 'main@origin..main@upstream'`, and deliberately merge/rebase the desired
commits into the migration bookmark. Run checks before pushing to `origin`.
Never deploy upstream directly. `just rollback COMMIT` tests and switches to a
selected older committed configuration. Existing system generations are also
available in the EFI boot menu. System rollback does not undo database migrations;
restore a compatible protected snapshot as well.

## Isolation and service state

Every staged media process uses the `nixflix-staging` network namespace. It has
only loopback, no physical interface, default route, or internet access. The NAS
is mounted read-only at `/data`. Native Plex sees `/data/media` at `/media`.
Stash retains `/data`, `/generated`, `/metadata`, `/cache`, and `/root/.stash`.
No media ports are exposed on the LAN. Inspect services through
`sudo ip netns exec nixflix-staging COMMAND` on .18.

Services require a real CIFS mount, stop when it disappears, and require a
root-owned `/var/lib/nixflix-migration/ready/UNIT` marker before they start.
Validated restored services start through `nixflix-staging.target` after reboot.
The readiness markers and namespace remain mandatory because copied configurations
contain live production identities and schedules. Do not remove
namespace or read-only protections to work around staging errors. The staging
slice has a 10 GiB memory-high threshold and 12 GiB maximum on the 16 GiB VM.

Automatic Arr reconciliation is disabled on this host to preserve restored
roots, monitored status, history and paths. The reusable modules still integrate
all four instances with Prowlarr, download clients, SAB categories and Recyclarr.
Profiles must exist before running `scripts/reassign-profiles.py` inside the
namespace as root. It updates only qualityProfileId, requests no file moves,
checks paths/monitored status after all updates, updates import-list and Radarr
collection profile references, then deletes obsolete profiles. Individual collection
updates avoid the bulk endpoint that would enqueue a collection refresh.

| Source | Target | Port | Managed profile |
| --- | --- | --- | --- |
| sonarr2 | sonarr | 8990 | WEB-1080p (Alternative) |
| sonarr | sonarr-4k | 8989 | WEB-2160p (Alternative) |
| radarr2 | radarr | 7879 | [SQP] SQP-1 (1080p) |
| radarr | radarr-4k | 7878 | [SQP] SQP-1 (2160p) |

Two Bazarr instances remain necessary for the separate Sonarr/Radarr pairs;
ports are 6767 and 6777. Native Seerr is independent of the Jellyfin-oriented
nixflix module. Its first startup migrates a **copy** of Overseerr state, per
[Seerr's migration guide](https://docs.seerr.dev/migration-guide/). Plex uses the
public package and preserved preferences/identity; Plex Pass is account-bound.
A cloned identity must remain isolated until the final cutover.

## Secrets

SecretSpec declares required credentials in `secretspec.toml`. Following the
[pass provider convention](https://secretspec.dev/providers/pass/), entries are
`secretspec/nixflix/default/NAME`. `scripts/extract-source-secrets.py` runs as root
on Ubuntu and streams its output directly to `scripts/import-pass.py` on .18.
No private SSH key is transferred. The target has a locally generated GPG identity;
its bootstrap key has no passphrase and is protected by the marty account's file
permissions. Add a passphrase/re-encrypt to your preferred key when convenient.
Runtime services never invoke GPG or pass.

From a checkout on .18, use `nix run .#provision`. It resolves through
pass, then atomically installs a generation under `/var/lib/nixflix-secrets`.
Root owns the directory (0700) and files (0600). The `current` symlink is switched
only after all required values validate. Arr uses systemd `LoadCredential` for
private runtime copies. Repeating provisioning with unchanged values is a no-op.
To rotate, use `secretspec set NAME --provider pass`, provision, and restart the
consumer. Remount `/data` for SMB credential changes. Older credential generations
remain root-only for deliberate rollback and may be removed after validation.
Other provider credentials and application tokens remain in the protected copied
application configuration; enter replacements through pass rather than Nix literals.

## Backups and cutover

Protected snapshots live under `/var/lib/nixflix-migration` on both hosts, outside
the repository. `scripts/snapshot.py` uses SQLite's backup API for live databases,
records timestamps, and copies Plex's latest dated library backups. Plex metadata
and preferences are copied while production runs: this is a staging snapshot,
not a final consistent cutover backup. SAB's queue and non-SQLite settings are
also provisional. Archive Ombi and Wizarr; leave unrelated Ubuntu services alone.

Before later cutover, take final consistent snapshots with source writers stopped,
verify restored counts/history and service destinations, and explicitly plan
routing changes. Do not bulk-search, rename, move media, or enable library-wide
upgrades. Assess concurrent memory pressure first. Intel passthrough is now
present and synthetic encoding tests pass. End-to-end Plex playback and HDR tone
mapping remain cutover checks, including live Plex Pass entitlement verification.

## Verified preparation, 2026-09-07

The root partition now starts at the original sector 2101248 and has size
260042719 sectors. ext4 reports 122 GiB. Filesystem UUIDs, EFI, NetworkManager,
stateVersion and the existing `xen-guest-agent` service were retained. Partition
backups and the original `/etc/nixos` configuration are in
`/var/lib/nixflix-migration/bootstrap` on .18.

The source and target each hold `snapshot-2026-09-07` (approximately 16 GiB).
Plex's library and blobs databases use dated 2026-09-07 backups. All state is on
local ext4; the NAS supplies only read-only media during staging. The live Ubuntu
services were not stopped. drbrown has the explicitly approved passwordless sudo
rule `/etc/sudoers.d/nixflix-migration`. marty is the target administrator; the
nixos account was removed after a separate key-authenticated sudo session passed.

Verified restored Arr counts, paths, monitored flags and history:

| Instance | Titles / artists | History rows |
| --- | ---: | ---: |
| Sonarr HD | 195 | 21435 |
| Sonarr 4K | 70 | 7801 |
| Radarr HD | 402 | 833 |
| Radarr 4K | 166 | 411 |
| Lidarr | 4 | 489 |

All four managed profiles were synced from the locked TRaSH resources, titles and
remaining profile references reassigned, and obsolete profiles removed. Prowlarr
applications and Arr SAB clients point to the local isolated endpoints. SAB retains
copied settings and queue state, adding the four managed categories plus Lidarr.
Seerr retains 4 users, 662 media records and 354 requests, with all four destinations
pointing at the new profile IDs. Its database and Audiobookshelf's database passed
SQLite quick_check. Plex retained its machine identifiers and token, and returned
five authenticated library sections using the original `/media` paths. Its cloud
subscription endpoint is inaccessible in isolation; live entitlement and hardware
transcoding validation remain for cutover/GPU work.

All 18 HTTP ports responded during staging (Plex requires authentication).
Concurrent startup and library/API checks used about 2.7 GiB in the staging slice;
its memory-high threshold was reached, with zero OOM kills observed. This is limited
headroom for heavy scans or transcoding: that initial 4 GiB allocation was not
production capacity validation. See the later RAM/GPU verification below.

`test-isolation.py` verified missing API credentials prevent startup and NAS loss
stops all media units without local fallback writes, then restored the services.
Repeated SecretSpec provisioning kept the same generation. The reusable Arr helper
now explicitly checks credentials before starting, fixing a fallback-to-empty-key
behavior found by this test. Recyclarr state/configuration permissions are 0700/0600.

Useful operations on .18:

```sh
sudo systemctl status nixflix-staging.target
sudo ip netns exec nixflix-staging curl http://127.0.0.1:5055/api/v1/status
sudo nix run .#validate-state -- /var/lib/nixflix-migration/snapshot-2026-09-07
# Temporarily interrupts ONLY staged services and restores them:
sudo nix run .#test-isolation
```

To inspect a staged UI from the workstation without allowing outbound traffic,
run a localhost-only relay on .18, then an SSH tunnel from the workstation:

```sh
# On .18, for Seerr:
sudo socat TCP-LISTEN:15055,bind=127.0.0.1,reuseaddr,fork EXEC:'ip netns exec nixflix-staging socat STDIO TCP:127.0.0.1:5055'
# On the workstation, in another terminal:
ssh -F /dev/null -L 15055:127.0.0.1:15055 marty@10.69.0.18
```

Browse `http://localhost:15055`; stop the relay when finished. Plex cloud sign-in
and external notifications/downloads are intentionally unavailable in isolation.
For later GPU validation set `nixflixHost.gpuPassthrough.enable = true` only after
passthrough exists, then test VA-API and real Plex/Stash transcoding. Production
cutover still requires a final consistent transfer, tested cloud authentication,
provider credentials, deliberate routing changes, and a memory/concurrency decision.


## RAM, GPU, notifications and proxy preparation

The VM now has 16 GiB RAM and Intel UHD 750 (`8086:4c8a`) passthrough.
The staging slice allows 10 GiB before throttling and 12 GiB maximum, retaining
headroom for the OS and Nix builds. Plex receives the render device. Stash uses
the host's pinned FFmpeg and Intel driver through read-only store/driver mounts;
the preserved Alpine image does not include the Intel userspace driver.

A NAS recovery timer retries a failed boot mount every minute and starts ready
staging services when connectivity returns. Stop `nixflix-nas-recover.timer` and
its service before intentionally unmounting the NAS for maintenance.

Notifiarr is removed from the target service definitions; its snapshots and
application state remain available. Apprise API is pinned by digest and prepared
for Discord plus Matrix. It has no published container port or proxy route.
Upstream Notif covers HD/4K Sonarr and Radarr plus Lidarr, preserves unmanaged
connections during migration, and resolves arbitrary secret fields at runtime.
Its configuration jobs are manual during staging.

Provision on `.18` as marty, using hidden pass input (values never enter shell
history):

```sh
pass insert secretspec/nixflix/notifications/DISCORD_APPRISE_URL
pass insert secretspec/nixflix/notifications/MATRIX_APPRISE_URL
nix run .#provision-notifications
```

The values are Apprise destination URLs: `discord://WEBHOOK_ID/WEBHOOK_TOKEN`
and `matrixs://ACCESS_TOKEN@HOMESERVER/!ROOM_ID` (URL-encode credentials where
required). The installer requires both, writes an atomic root-owned mode-0600
JSON/YAML configuration outside the Nix store, and is safe to repeat. Runtime
copies are mode 0400 and readable only by the dedicated Apprise user.
Provisioning alone does not start delivery. A ready marker and explicit testing
are required before activating Apprise and the Arr notification jobs.

Seerr's managed pre-start prepares an Apprise webhook for request/approval,
availability and issue events, disabled during staging. It preserves a local
backup of the old settings. Approval messages link to authenticated Seerr at
`https://seeme.dalebox.pw/requests`; there is no unauthenticated approval endpoint
or embedded API key. At production activation, enable this webhook deliberately
and remove the staging pre-start's forced disabled setting.

Caddy uses upstream's virtual-host helpers inside the loopback-only namespace.
The existing `seeme.dalebox.pw` request hostname is preserved. Other generated
service subdomains under `dalebox.pw` are prepared routes, not published DNS.
The current Cloudflare tunnel terminates HTTPS; the staged Caddy origin uses
HTTP. Existing `.12` tunnel routes are unchanged. Keep Apprise's API private
when production networking is implemented. `notify.816913.xyz` still routes to
source Notifiarr and should be retired deliberately at cutover; Matrix and
other unrelated tunnel routes must remain intact.

## Verification after RAM and GPU upgrade

After adding Linux firmware and `i915 enable_guc=2`, a reboot loaded the Rocket
Lake DMC firmware and authenticated HuC for all workloads. Before this fix a
synthetic encode hung the GPU; after reboot, H.264 and 10-bit HEVC VA-API encoding
both completed successfully inside Stash. Stash itself detects H.264 and VP9
VA-API encoders. Its v0.29.3 release ignores arbitrary FFmpeg environment
variables, so a managed pre-start updates the supported YAML keys atomically.
Plex retains `HardwareAcceleratedCodecs=1` and its service user can access VA-API.

All restored Arr library identities, paths, monitored flags and history still
match the protected snapshot. Missing-credential and missing-NAS tests passed
again through the `test-isolation` flake app and restored staged services.
The Seerr Caddy route returns HTTP 200 after following its login redirect.
Apprise's exact pinned image parsed both destination formats and started with
restricted read-only configuration in an isolated test container. Locked config
read, write and delete APIs returned HTTP 403. No real notifications were sent.
Real Discord/Matrix credentials and end-to-end delivery remain pending.

Use `nix develop -c python3` for ad hoc Python. Packaged migration commands use
their pinned Python and tool dependencies through `nix run .#APP`; `just` recipes
remain shortcuts. `deploy`, `snapshot`, `restore`, `configure-staging`,
`reassign-profiles`, `validate-state`, `test-isolation`, `provision`, and
`provision-notifications` are available. Run source snapshot tools on Ubuntu;
target state/provisioning tools on `.18`; deployment from the workstation's jj
checkout. API-based migration tools must execute inside the staging namespace.
