# Arr application releases

Production, staging, and hosted VM tests select Radarr (both instances) and Lidarr
from the locked `nixpkgs-media` input. Prowlarr also uses that input when it reaches
the reviewed minimum release; until then, it uses the official stable Linux archive
in `pkgs/prowlarr-upstream/sources.json`. Its bundled .NET runtime is pinned with
the release, so runtime security fixes require refreshing this fallback as well.

Run `python3 scripts/update-prowlarr.py` on the VM to refresh both supported Linux
architectures. The helper downloads each archive and checks GitHub's published
SHA-256 digest before updating any pins. Review the release notes and diff, run
`nix fmt` and the non-VM checks/builds on the VM, then run integration tests in
hosted CI before deployment. Do not enable nested virtualization on production.

Before major app upgrades, stop the affected services and take an age-encrypted
backup of their configuration and SQLite databases. Nix generation rollback does
not undo database migrations; preserve the backup until the new release is proven.

For stale indexer warnings, test the existing indexer through each affected app,
then run its `CheckHealth` command. On Radarr, `POST /api/v3/indexer/testall`
exercises the stored indexer IDs and clears the backoff after a successful test. A capabilities test can succeed while an old
failure record remains, so verify the health API afterward. Do not disable health
checks or remove indexers to suppress warnings.
