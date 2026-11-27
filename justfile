# All recipes run in the pinned environment: nix develop -c just <recipe>
set shell := ["bash", "-euo", "pipefail", "-c"]

check:
    python3 -m unittest discover -s tests/migration -v
    nix eval .#nixosConfigurations.fateflix.config.system.build.toplevel.drvPath
    nix build .#checks.x86_64-linux.four-instance-eval
    nix build .#checks.x86_64-linux.production-eval
    treefmt --fail-on-change

# Build the current checkout in the local Nix store. Never activate it.
build:
    nix build --no-write-lock-file --no-link .#nixosConfigurations.fateflix.config.system.build.toplevel

# Optional development check only. Production activation belongs to Comin.
build-staging:
    nix build --no-write-lock-file --no-link .#nixosConfigurations.nixflix-staging.config.system.build.toplevel

# Run on .18 as marty from a checkout of this repository.
provision:
    nix run .#provision

# Run on .18. Provisioning does not enable outbound notifications.
provision-notifications:
    nix run .#provision-notifications
