# Completed Ubuntu migration archive

The Ubuntu-to-NixOS migration was a one-time operation and is complete. These
scripts are retained only for deliberate historical reuse. They are not normal
FateFlix operations. No service, timer or workflow executes a migration
operation. Old source addresses, container names and state paths need review before
any reuse. Merely evaluating the flake or displaying help performs no migration.

The former top-level apps (`snapshot`, `cutover-source`, `migrate-native`,
`route-seerr`, `restore`, `configure-staging`, `validate-state`, and
`reassign-profiles`) are intentionally removed. One explicitly manual entry point
replaces them:

```console
nix run .#legacy-ubuntu-migration -- --help
nix run .#legacy-ubuntu-migration -- --confirm-legacy-operation COMMAND [ARGS...]
```

The acknowledgement must precede `COMMAND`. Help lists the allowed commands;
invoking the app without a command only displays help. This is an operator guard,
not a security boundary for someone who explicitly executes an archived script.
`extract-source-secrets` and `import-pass` also belong to this historical workflow.
The latter delegates to the existing role-checked generic credential importer;
ordinary `provision` apps remain unchanged.

`snapshot` means an old Ubuntu application-state copy, not a VM snapshot. Xen
Orchestra VM snapshots are outside this repository's migration tooling scope.
No existing snapshots, runtime state or readiness markers are deleted or renamed.
In particular, `/var/lib/nixflix-migration/ready` and `nixflix-staging` systemd
names remain current NixOS readiness/isolation contracts despite their names.

Synthetic legacy tests are manual, separate from routine runtime CI:

```console
nix develop -c python3 -m unittest discover -s legacy/ubuntu-migration/tests -p 'test_*.py'
```

Routine CI retains its credential/runtime tests plus archive-boundary and safe
dispatcher tests. Its existing operations check builds the packaged app and runs
only its inert help paths, never a migration command.
See [current operations](../../docs/operations.md) and
[GitOps](../../docs/gitops.md), not the [historical runbook](../../docs/migration/nixflix.md),
for day-to-day operation.
