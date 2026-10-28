# Dependencies beyond Renovate

Run these from a Git checkout on the NixFlix VM:

```console
nix run .#update-extra-dependencies -- audit
nix run .#update-extra-dependencies -- refresh --dry-run
nix run .#update-extra-dependencies -- refresh
git diff
```

The default is the offline audit. Refresh requires a clean checkout and prepares
reviewable changes; it does not commit, push, merge or activate a system. It can
run on a completed Renovate branch or on `main`. Commit pending local work first.
The app supplies Git, Skopeo and the existing Jellyfin updater's tools.

## Inventory and ownership

The audit checks tracked Nix image/source/hash pins, every locked flake input,
the package release manifest and the container manifest. It verifies custom
manager discovery against the actual regular expressions in `renovate.json`.
Native packages and their transitive dependencies are covered by their locked
Nixpkgs package sets, rather than independent versions in capability modules.
The machine-readable ownership rules are `scripts/dependency-coverage.json`.
CI rejects newly discovered literal pins or manifest entries without ownership.

| Dependency | Update mechanism |
| --- | --- |
| Native services, kernel patches, Python/Node libraries, build and documentation tools | Renovate refreshes the three Nixpkgs locks; host release channel, kernel series and interpreter compatibility remain reviewed choices |
| Notifiarr, Maintainerr, Whisparr v2, Caddy replace-response | Renovate discovers versions/commits; the trusted artifact helper generates source and dependency hashes |
| Mylar3 and Stash | Renovate discovers container digests in `hosts/nixflix/containers.json` |
| Apprise | Supplemental refresh resolves `docker.io/caronc/apprise:latest`, requires Linux amd64 and pins the registry's top-level digest |
| Jellyfin plugin catalog | Supplemental refresh uses the existing ABI-aware source aggregator and verified download hashes |
| Navidrome generated plugin options | Existing artifact helper regenerates from the selected Nixpkgs plugin bundles when that lock changes |
| Other flake inputs, including upstream NixFlix and documentation theme | Renovate lock maintenance and trusted artifact fingerprint refresh; no parallel upstream publisher |
| TRaSH Guides and Recyclarr templates | Deliberate policy pins; automatic refresh excluded |
| Seerr 3.5.1 fallback | Minimum compatibility override; newer `nixpkgs-media` Seerr supersedes it automatically, removal/change requires review |
| Vendored plugin implementations and source list | Deliberate source snapshot with checked provenance; never overwritten by catalog refresh |
| Jellyfin examples and test plugin selections | Independent regression fixtures; never rewritten by supplemental discovery |
| Historical Readarr, Whisparr, Notifiarr, Bazarr, Audiobookshelf and Tautulli image entries | Retained migration records; these services run natively, so unused container pins are not refreshed |
| GitHub Actions and supported runtime declarations | Renovate's GitHub Actions manager |
| CI's PyYAML installation and Renovate validator | Exact pins in `.github/requirements-ci.txt` and `ci.yml`; Renovate requirements/custom managers keep them in the CI tooling group |

This is an audit of repository-owned pins, not a vulnerability scanner or an
inventory of live credentials, databases, media or remote service endpoints.
Review intentional ownership rules when adding a dependency in an existing
manual compatibility module; path ownership is not proof of runtime compatibility.

## Automatic hook

`update-packages.yml` runs supplemental discovery after a same-repository
Renovate package/lock/container PR is merged into `main`. The merged-event job
checks out trusted `main`; it never executes the PR head. Closing an unmerged PR
does not trigger discovery. Existing pre-merge artifact generation stays separate.

Sunday's existing 12:30 UTC schedule and workflow dispatch run the same updater.
It yields while any Renovate or automated update PR is open. Deferred work is
retried by a later scheduled/manual run. Concurrent supplemental jobs serialize.
When changes exist, the publisher opens `automated/extra-dependencies` and
explicitly dispatches CI. It does not merge the PR or write to `main`; Comin
continues to deploy only reviewed merges.

Discovery runs in a temporary detached Git worktree. Registry, platform,
manifest, hash or artifact-validation failures prevent any files being copied
back. A dirty or concurrently changed checkout is rejected. Only Apprise's image
reference and the Jellyfin catalog are allowed outputs; other Nix configuration
edits are rejected even in the allowed image file. Applying the prepared files
uses individual atomic replacements with rollback on ordinary write failures;
it is not a crash-atomic multi-file transaction.

The catalog retains previously verified entries and versions when sources
temporarily disappear. A previously published version changing bytes, or a
plugin changing identity, requires manual review. Intentional removals remain a
manual catalog edit. A successful refresh means the available catalogs were
processed, not that every remote repository was reachable.

## Organization transfer

The canonical repository is `dales-garage/fateflix`. On `marty@10.69.0.18`,
the administrator checkout is `/home/marty/fateflix`; its origin uses
`https://github.com/dales-garage/fateflix.git`. Upstream remains
`kiriwalawren/nixflix`. Internal NixFlix module names, service names and state
paths retain their existing names. Router configuration ownership comments
retain the original repository name so previously managed files remain recognized.

GitHub App installations belong to the account that installed them. Install
[Renovate](https://github.com/apps/renovate/installations/new) in `dales-garage`
and explicitly select `fateflix`, which remains a fork. The existing
`forkProcessing: enabled` configuration and dependency dashboard are retained.
Check other app installations under the organization's Settings → GitHub Apps.
GitHub Actions itself needs no separate app installation.

CI accepts merge queue `merge_group` events and compares the candidate against
`merge_group.base_sha`, including earlier queued changes. Before enabling a
merge queue for `main`, require `CI required` and choose the desired merge
method. A public organization repository supports merge queues on GitHub Free.
This migration does not enable a queue or change branch protection.
