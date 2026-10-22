# All recipes run in the pinned environment: nix develop -c just <recipe>
set shell := ["bash", "-euo", "pipefail", "-c"]

check:
    python3 -m unittest discover -s tests/migration -v
    nix eval .#nixosConfigurations.nixflix.config.system.build.toplevel.drvPath
    nix build .#checks.x86_64-linux.four-instance-eval
    nix build .#checks.x86_64-linux.production-eval
    treefmt --fail-on-change

build revision="migration/nixflix":
    nix run .#deploy -- build '{{revision}}'

test revision="migration/nixflix":
    nix run .#deploy -- test '{{revision}}'

switch revision="migration/nixflix":
    nix run .#deploy -- switch '{{revision}}'

# Test the selected old revision before making it the boot default.
rollback revision:
    nix run .#deploy -- test '{{revision}}'
    nix run .#deploy -- rollback '{{revision}}'

# Run on .18 as marty from a checkout of this repository.
provision:
    nix run .#provision

# Run on .18. Provisioning does not enable outbound notifications.
provision-notifications:
    nix run .#provision-notifications
