# FateFlix v2 validation

Baseline: pushed `fateflix` commit `368c67c`. Implementation branch: `fateflix-v2`.
The baseline contracts and SecretSpec declaration metadata are in
[fateflix-v2-baseline.json](fateflix-v2-baseline.json). No credential values were
captured. `flake.lock` remains byte-for-byte unchanged, SHA-256
`d9a2b1fa1f6e54b0c9faa4347f87cfb0af303c74f3e41e299f9c3fdfad12104f`.

Validation ran on the NixFlix VM in an isolated temporary checkout, without
activation, provisioning production credentials, or changing media:

- Full `nix flake check --no-build --show-trace` evaluation passed. The retained
  source-only IFD was realized first. The default x86_64 system was checked;
  aarch64 builds were not performed.
- Both production and staging derivations were explicitly evaluated and both
  x86_64 system closures built successfully.
- All 14 non-VM checks passed, including formatting, generated-flake consistency,
  documentation, Nix unit checks and host evaluation regressions.
- All 167 Python regression tests passed, including provider selection, separate
  staging declarations, rejected production-only provisioning and interrupted
  generation recovery.
- Runtime-generated secret canaries stayed out of both built configurations,
  recursive derivations and build output. Temporary credential generations were
  created outside the repository and removed after verification.

Production contracts preserve identities, UID/GID assignments, package versions,
mounts, container images, database locations and runtime credential filenames.
The firewall rule set is unchanged; module composition changes the ordering of
independent allow rules. Operations metadata adds the canonical storage root and
mount-unit name. SABnzbd's declared directories now match the inspected restored
settings: `/data/usenet/intermediate` and `/data/usenet/`.

Staging preserves the same numeric identities while excluding Comin, production
health/deployment units, Apprise and notification jobs. It installs its own role
marker and independent `nixflix-staging` SecretSpec manifest. Capacity settings
and the shared profile evaluate without deployment importing their declarations.

The VM has no `/dev/kvm`. KVM integration scenarios were evaluated but **not
executed** here; the affected-test planner selects the full guest suite for the
shared integration relocations, and CI retains KVM-capable runners for those
jobs. Their execution remains pending CI.

**Live staging deployment and rollback remain unverified.** There is no separate
live staging target for this acceptance step. Comin's source is unchanged and no
production activation occurred. V2 must not be labelled deployment-ready until
live staging acceptance passes.

## Final verification scope

An overlapping evaluation/documentation rerun previously stopped responding over
SSH. Access returned after a VM reboot; prior-boot kernel diagnostics contained
no OOM or lockup entry, so the cause is unconfirmed. The existing homepage HTTP
route responds with status 200 again. Subsequent checks run sequentially with
explicit resource limits. The final full flake evaluation passed in a 9 GiB
user scope, with a measured peak of about 8.7 GiB.

A disposable qBittorrent guest passed its functional assertions through
`nix shell` after a separate QEMU/TCG boot wait. The larger Caddy guest hit startup
timeouts under software emulation. These runs do not establish a passing full
integration suite. Experimental guest testing was stopped at the user's request.

The selected acceptance route is evaluation and both system builds on the NixOS
VM while v1 remains active. No activation or nested VM is needed for those
checks. KVM integration tests and live staging deployment/rollback remain
unverified.

FreeCORE telemetry now has an explicit `freecore` aspect and
`modules/_modules/monitoring/freecore.nix` implementation. It owns the existing
SMB/HTTPS availability checks and exposes the unchanged NAS bridge payload in
production. The NAS address lives in `modules/_hosts/nixflix/freecore.nix`.
Regression checks confirm staging has neither the payload nor the probes, and
both host closures build with the module included.
