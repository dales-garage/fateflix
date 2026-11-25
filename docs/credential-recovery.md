# Credential generation recovery

Run provisioning through SecretSpec and age-backed Passage. The provider is still
named `pass`: FateFlix supplies a `pass` CLI bridge to Passage in the host,
development shell, and provisioning apps. It is not SecretSpec's native `age`
provider and does not require changing the pinned SecretSpec version.

To migrate every entry on the VM as marty:

```sh
nix run .#migrate-secrets-to-passage
```

The migration generates a private age identity at `~/.passage/identities`, encrypts
to a temporary store, and compares every decrypted value byte for byte before
publishing `~/.passage/store`. Entry paths and multiline contents are preserved.
An existing destination must already match; it is never overwritten. Errors
suppress credential values. The original `~/.password-store` and GPG identity are
retained for rollback. Keep a protected recovery copy of the age identity before
retiring those backups. Only the migration command needs GPG.

Use `passage show ENTRY`, `passage insert ENTRY`, or the compatible `pass` command.
Continue to use `secretspec set NAME --provider pass` and `nix run .#provision`.
Secrets live outside the repository and Nix store. Service runtime credential
paths and namespace separation remain unchanged.

The dedicated `capabilities/secrets/secretspec-indexers.toml` manifest declares
an `indexers` profile for DOGnzb primary and secondary, Tabula Rasa, and NZBPlanet.
Use that file and profile explicitly when managing those keys. Keeping the
manifest separate avoids inheriting default application credentials into the
indexer profile. Migration does not change application-side indexer settings.

The installer
validates the complete input before creating a new generation. Missing credential
files and file/directory ownership or permission drift cause a complete private
replacement generation; an unchanged valid generation remains selected without
rewriting it. The installer does not repair an untrusted root credential directory
owner in place.

Each new credential is written and synced, and the generation directory is synced,
before the `current` symlink changes atomically. Preparation failure preserves the
previous selection. A failure syncing the parent after publication restores the
previous symlink. Incomplete old generations remain available for inspection and
are not modified. Errors suppress credential values. Keep root directory and
generation modes at 0700 and credential file modes at 0600.

Regression tests cover incomplete generations, file and directory mode drift,
ownership drift, unchanged generations, interrupted replacement, and a final
parent-directory sync failure. Run the Python suite with PyYAML installed:

```sh
python -m unittest discover -s tests/migration -p 'test_*.py'
```

Jellyfin's unit and VM manifest fixtures now use `builtins.toFile`, so contents
and hashes exist during evaluation without first building generated store paths.
The existing assertions remain in place. Minimal standalone evaluation fixtures
set `system.stateVersion = "26.05"`. Validate the fixture repair with a new
`XDG_CACHE_HOME` and then the same warm cache using `nix flake check --no-build`,
and build `checks.x86_64-linux.unit-tests`.

Nix generations restore software/configuration, not application databases.
Application backup automation remains deferred to the planned Xen Orchestra
work. No database migrations or automatic data rollback are part of this change.

## NNTP accounts

All SAB NNTP usernames and passwords are stored in the age-backed Passage vault
under `secretspec/nixflix/nntp/`. The dedicated `secretspec-nntp.toml` manifest has
only the `nntp` profile, avoiding default-profile inheritance. It contains the
username/password pairs for NGD, Usenet Farm, Viper, Supernews and Eweka.

On the production VM, resolve and install them without printing values:

```sh
nix run .#provision-nntp
```

This publishes an atomic root-owned generation beneath
`/var/lib/nixflix-nntp-secrets/current` (directories 0700, files 0600). It does not
replace the existing application/SMB secret generation. SAB receives these files
through systemd `LoadCredential`; its startup helper applies the public endpoint
policy in `capabilities/downloads/nntp-servers.json` to the existing configuration.
Credential values are never embedded in Nix expressions or stored in Git.

After rotating values and provisioning, restart SAB during an appropriate queue
window so systemd loads the new generation. Current endpoint policy uses strict
TLS on port 563, moves Viper to `viper.newsgroupdirect.com`, disables the duplicate
US NGD entry, and uses a 40-connection pool for the 250 Mbps link. Client retention caps are 0;
SAB uses a 30,000,000 bytes/s cap at 100%, and a dedicated prowlarr category.
Other queue, path and priority settings are preserved. Existing Supernews and
Eweka values are also managed through this profile.

The installed VM has an equivalent persistent bootstrap override at
`/etc/systemd/system.control/sabnzbd.service.d/90-fateflix-nntp.conf`; the flake
contains the same integration for future deployments. It can be removed after a
flake deployment includes the NNTP hooks, to avoid duplicate idempotent startup
application. Staging cannot provision these production credentials.

## Indexer quota and downloader guardrails

`capabilities/downloads/usenet-policy.json` declares conservative paid-account
query/grab limits per rolling 24 hours. These are local operating budgets, not
claims about the exact purchased subscription tier. Tabula Rasa uses 1800 queries
and 100 grabs against the owner's upcoming 2000-request daily allowance; provider
429 backoff remains authoritative until the upgraded allowance is active.

The existing `fateflix-download-policy` service applies this public policy after
its protocol checks. The updater keeps provider keys intact, writes only changed
quota fields, and tests the direct SAB client before repairing its localhost
route and dedicated `prowlarr` category. It does not trigger upstream indexer
tests or searches. The VM has an equivalent persistent bootstrap post-start hook.

SAB's public NNTP policy sets every server's client-side retention to 0 and uses
40 total enabled connections: NGD US 10, NGD EU 4, Supernews 6, Farm 6, Viper 4,
Eweka 10. Existing server priorities are retained. The 30,000,000 bytes/s cap is
240 Mbps, giving the confirmed 250 Mbps connection modest headroom. No synthetic
bulk downloads were launched to benchmark it.
