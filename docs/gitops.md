# nixflix GitOps operations

Production is `declarative-dale/nixflix` → reviewed `main` → Comin →
`nixosConfigurations.nixflix-production`. Comin polls every 60 seconds and uses
`switch`, making deployments persistent. Reboots are manual. The staging output
has Comin disabled; there is no separate staging VM in this rollout.

## GitHub setup and promotion

Install the [Mend Renovate GitHub App](https://github.com/apps/renovate) for this
repository only. App installation requires the repository owner's browser login;
repository configuration alone cannot install it. `renovate.json` explicitly
enables fork processing and the Nix manager.

Protect `main` with the `CI required` check, strict/up-to-date status checks,
required PRs (zero additional approving reviews for this single-owner repo),
and disabled force pushes/deletion. Keep merge commits enabled for upstream
syncs. Disable repository automerge. Allow Actions to create PRs, keeping the
default token read-only; only the update jobs request write permissions.

The implementation branch includes the original migration history and an upstream
merge commit. Review the upstream reconciliation separately from Comin changes.
Merge only after the required CI check passes. Do not enable Comin against the old
`main`, which does not contain the production host configuration.

## Update ownership

| Group | Updates | Owner |
| --- | --- | --- |
| System dependencies | Flake lock revisions, Caddy replace-response commit/hash, Navidrome generated plugin options | Renovate plus artifact helper |
| Media applications | Mylar3/Stash digests, Maintainerr, Notifiarr, ABI-compatible Jellyfin plugin manifests | Renovate plus artifact helper |
| CI tooling | GitHub Actions and runtime versions recognized by that manager | Renovate |
| Major upgrades | Explicit major releases stay in separate PRs | Renovate; manual review |
| Upstream nixflix | Upstream merge commits | `upstream-sync.yml`; Sunday 12:00 UTC or manual |
| TRaSH/Recyclarr policy and NixOS release channel | Deliberate policy/release changes | Owner; excluded from automatic upgrades |

Renovate allows one active branch/PR at a time, with a daily 06:00–10:59
America/Chicago window. A subsequent bot run can open the next group after a
merge; merges remain manual. Weekly flake lock maintenance runs on Sunday in
that window. Grouping reduces repeated rebases; unrelated main changes can still
require a group to rebase. Security alerts may bypass Renovate's regular PR limit.

Renovate owns package discovery through `.github/package-versions.json`:
Notifiarr and Maintainerr use stable GitHub releases; Caddy's replace-response
plugin tracks an exact commit on its existing master branch. The Caddy server
itself and Navidrome plugin packages follow nixpkgs. Digest updates to `latest`
container tags have no reliable semantic-major classification and remain in the
media group for review. Jellyfin's plugin versions use upstream ABI metadata,
not application-wide semantic versioning; refreshing the catalog does not enable
plugins or change the independently pinned test/example selections.

The hosted Renovate app cannot run our Nix hash-generation scripts. On its PRs,
`update-packages.yml` runs reviewed **base-branch** scripts with read-only
permissions, importing only validated version and lock JSON from the candidate.
It regenerates Notifiarr's architecture hashes, Maintainerr's source/Yarn hashes,
and Caddy's plugin hash as needed. A nixpkgs revision change also regenerates
Navidrome options and Caddy's hash. Media changes refresh Jellyfin's ABI-aware
manifest catalog on that same PR. Manual pushes do not trigger regeneration; use the local refresh command below.
The separate publisher only writes allowlisted
generated files, rejects a changed PR head, and never force-pushes. Its bot author
is ignored by Renovate's manual-edit detection so normal rebasing remains enabled.

An input fingerprint in `.github/update-artifacts.json` prevents CI from building
or accepting a version-only change before its hashes are generated. An initial
Renovate commit can briefly show this pending-artifact failure; the helper commits
the artifacts and explicitly dispatches CI on the completed branch. A failed
helper leaves the PR blocked. Input repository/channel changes require manual
artifact preparation rather than executing arbitrary PR-provided flakes. For a
manual update, edit the version manifest/lock first, then run
`python3 scripts/renovate-artifacts.py refresh --base origin/main`, review the
resulting diff, and commit it with the input change. This command runs local
scripts and does not publish or merge anything.

Jellyfin manifests cannot be discovered reliably through generic GitHub releases:
they combine multiple upstream catalogs and Jellyfin ABI constraints. A Sunday
12:30 UTC/manual fallback creates one `automated/media-applications` PR when no
Renovate or other automated update PR is open. The five independent scheduled
package updater jobs have been removed. The fallback is outside Renovate's PR
counter; a later Renovate run can still open its own PR while that fallback is open.

Historical container pins and disabled Apprise are excluded. TRaSH/Recyclarr
policy URLs stay pinned to reviewed revisions in `flake.nix`: disabling a package
rule alone does not stop lock maintenance advancing an unpinned input. Nix digest
pinning stays disabled for branch-only flake URLs; the lock file supplies pins.
The host stays on NixOS 26.05. Optional Jellyfin/Navidrome modules remain maintained
without enabling them on production. The inherited omnibus updater is not scheduled.

Upstream merge conflicts abort without publishing a partial merge. Existing
upstream/fallback PRs are left untouched. Check policy pins and workflows during
upstream review. Actions uses `GITHUB_TOKEN`, not a PAT or production credentials;
token-created commits explicitly dispatch `ci.yml` to run CI automatically. GitHub
also creates a separate approval-held `pull_request` run for bot-created PRs.
Live testing found that this can keep the PR blocked even after dispatched CI
passes. After reviewing the generated diff, approve that specific workflow run;
GitHub may run CI again. The explicit dispatch does not replace this approval.
Fully automatic triggering requires separate GitHub App or PAT credentials, which
this repository does not provision. See
[GitHub's workflow-trigger behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

CI compares each check's Nix derivation and the production derivation against the
PR base (or previous main commit). Only affected checks run, including the union
of changes in a grouped PR. Shared dependency changes select their transitive
dependents. Missing/broken base evaluation selects the full suite; head evaluation
errors fail CI. `CI required` permits skips only for checks the plan did not select.
CI does not deploy or contact the VM.

## First deployment

Prerequisites: reviewed main with passing CI, SSH access as `marty`, sufficient
space on `/` and `/boot`, a fresh hypervisor snapshot, and consistent application
backups. Stop application writers while taking the final backup of databases,
settings, and queues; retain SecretSpec/pass recovery material separately. Old
September migration snapshots are not current backups.

On the VM, clone the reviewed repository and run:

```sh
git clone https://github.com/declarative-dale/nixflix.git
cd nixflix
sudo bash scripts/gitops-bootstrap.sh /absolute/path/to/completed-backup
sudo comin status
sudo nixflix-health check
sudo cat /var/lib/nixflix-gitops/deployed.json
```

The bootstrap script records the prior system and copies `/etc/nixos` into
`/var/lib/nixflix-gitops`, builds the exact main SHA, switches persistently, then
removes the obsolete local flake/lock. `/etc/nixos/configuration.nix` explains
Comin ownership rather than retaining a stale independent deployment source.
The supplied backup directory records the operator's backup; the script does not
create a VM snapshot or establish that an arbitrary directory is a valid backup.
An operator who explicitly chooses to proceed without a fresh backup can pass
`--skip-backup`; that choice is recorded in `bootstrap-backup`.

SecretSpec/pass provisioning repairs incomplete generations and permission drift atomically; see [credential recovery](credential-recovery.md). Comin fetches the public
repository without credentials. No API keys or GitHub write tokens enter Git or
the Nix store. The old `deploy.py` refuses activation once Comin owns the machine.

## Health and recovery

```sh
sudo comin status
sudo journalctl -u comin -u nixflix-health --since '-30 minutes'
sudo cat /var/lib/nixflix-gitops/health.json
curl --fail http://127.0.0.1:9199/health
```

Health uses live systemd, HTTP and authenticated API checks, locally cached NAS access/mount mode,
credential permissions, Seerr webhook configuration, and Notifiarr connections.
It never writes media or relies on historical ready-marker files. The report is
root-only. The loopback endpoint returns only healthy/unhealthy, rejects reports
older than 15 minutes or from another boot/generation, and exposes build/deploy
failures to Notifiarr's HTTP service checker. Notifiarr notification delivery
depends on the account's existing service-notification configuration and an
available Notifiarr client; journals remain available independently.

`deployed.json` records successful Comin activation, not proof of application
health. Automated checks allow up to two minutes for restarted services to become
ready before failing; manual checks return immediately unless `--wait` is given.
A build failure leaves the running generation intact. A post-activation
health failure does not automatically roll back. Cloud Plex webhooks and remote
notification delivery must be checked during rollout; the periodic probe uses
Plex's local API so cloud outages do not mark the VM unhealthy.

For recovery, suspend Comin and wait until `comin status` shows no deployment in
progress. Keep the daemon suspended while selecting a known-good generation:

```sh
sudo comin suspend
sudo comin status
sudo nix-env --profile /nix/var/nix/profiles/system-profiles/comin --list-generations
# Select a known-good generation from the list, then:
sudo nix-env --profile /nix/var/nix/profiles/system-profiles/comin --switch-generation GENERATION
sudo /nix/var/nix/profiles/system-profiles/comin/bin/switch-to-configuration switch
```

Comin generations live in `system-profiles/comin`; the original bootstrap and
pre-Comin generations are separately available in `/nix/var/nix/profiles/system`.
Keep Comin suspended until a reviewed revert/fix commit has merged into main.
Do not restart Comin or reboot before the fix: suspension is process-local.
Use a new revert commit, never a backward force push (Comin requires forward
history). Restart/resume with `sudo systemctl start comin` and `sudo comin resume`,
then check deployment and health. If activation changed database schemas, restore
the matching application backups before restarting the older application; a Nix
generation rollback alone does not reverse database migrations.

Keep three bootable Comin generations. During a separately scheduled reboot,
verify SSH, NAS, services and Comin return automatically. Finally merge a harmless
configuration change and confirm its SHA is deployed automatically. These live
acceptance checks require access to the VM and are not implied by passing CI.

Capacity advisories, maintenance holds, retention reports, and the staged
acceptance procedure are documented in [operations](operations.md).
