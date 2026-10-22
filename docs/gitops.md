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

| Updates | Owner | Review policy |
| --- | --- | --- |
| Direct flake inputs and lock revisions | Renovate | Sunday 06:00–10:59 America/Chicago; manual merge |
| Actions and active Mylar3/Stash image digests | Renovate | Separate from flake updates; major updates separate |
| Upstream nixflix | `upstream-sync.yml` | Sunday 12:00 UTC or manual; merge commit required |
| Notifiarr, Maintainerr, Caddy and plugin hashes | `update-packages.yml` | Sunday 12:30 UTC or manual; one PR per updater |
| TRaSH/Recyclarr policy inputs | Owner | Deliberate policy review; excluded from Renovate |
| NixOS release channel | Owner | Explicit release-upgrade PR; never change stateVersion |

UTC workflow schedules run at 06:00/06:30 CST or 07:00/07:30 CDT. Renovate allows
five concurrent PRs. Historical container pins and disabled Apprise are excluded.
Full-lock maintenance is disabled so it cannot bypass the media-policy exclusions;
Renovate updates individual input locks instead. The inherited omnibus updater is
not scheduled. Optional Jellyfin/Navidrome modules remain maintained for the fork,
without enabling them on the production host.

Custom workflows have explicit changed-file allowlists, detect no-op updates, and
leave existing open update PRs untouched. Merge/delete the bot branch before the
next run. Upstream merge conflicts abort without pushing; Actions' job summary
lists the files. They cannot overwrite your personal modules or silently resolve
conflicting workflows. Check any upstream changes to policy pins during review.

Actions creates PRs with `GITHUB_TOKEN`, then explicitly dispatches `ci.yml` at the
bot branch because token-created PRs do not recursively trigger workflows. No PAT
or production secrets are used. CI builds the production system, existing checks,
and GitOps tooling. Every dependency job must pass `CI required`, including after
manual dispatch. CI does not deploy or contact the VM.

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

Existing SecretSpec/pass provisioning remains unchanged. Comin fetches the public
repository without credentials. No API keys or GitHub write tokens enter Git or
the Nix store. The old `deploy.py` refuses activation once Comin owns the machine.

## Health and recovery

```sh
sudo comin status
sudo journalctl -u comin -u nixflix-health --since '-30 minutes'
sudo cat /var/lib/nixflix-gitops/health.json
curl --fail http://127.0.0.1:9199/health
```

Health uses live systemd, HTTP and authenticated API checks, NAS mount mode,
credential permissions, Seerr webhook configuration, and Notifiarr connections.
It never writes media or relies on historical ready-marker files. The report is
root-only. The loopback endpoint returns only healthy/unhealthy, rejects reports
older than 15 minutes or from another boot/generation, and exposes build/deploy
failures to Notifiarr's HTTP service checker. Notifiarr notification delivery
depends on the account's existing service-notification configuration and an
available Notifiarr client; journals remain available independently.

`deployed.json` records successful Comin activation, not proof of application
health. A build failure leaves the running generation intact. A post-activation
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
