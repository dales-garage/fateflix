# Credential generation recovery

Run provisioning through the existing SecretSpec/pass workflow. The installer
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
