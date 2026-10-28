#!/usr/bin/env bash
# Run on nixflix after reviewed main has passed CI and fresh backups exist.
set -euo pipefail
if [[ $EUID != 0 || $(hostname) != nixflix ]]; then
  echo 'Run as root on nixflix.' >&2
  exit 1
fi
backup_dir=${1:?Usage: gitops-bootstrap.sh /absolute/path/to/fresh-consistent-backup or --skip-backup}
if [[ $backup_dir != --skip-backup && ( $backup_dir != /* || ! -d $backup_dir ) ]]; then
  echo 'Supply the absolute directory of the completed application-consistent backup.' >&2
  exit 1
fi
if [[ -e /etc/nixos/README.gitops ]]; then
  echo 'Already managed by Comin; use PRs for updates.' >&2
  exit 1
fi
commit=$(git ls-remote https://github.com/dales-garage/fateflix.git refs/heads/main | cut -f1)
[[ $commit =~ ^[0-9a-f]{40}$ ]]
install -d -m 0700 /var/lib/nixflix-gitops
if [[ ! -e /var/lib/nixflix-gitops/bootstrap-entrypoint ]]; then
  cp -a /etc/nixos /var/lib/nixflix-gitops/bootstrap-entrypoint
fi
readlink -f /nix/var/nix/profiles/system > /var/lib/nixflix-gitops/bootstrap-system
printf '%s\n' "$backup_dir" > /var/lib/nixflix-gitops/bootstrap-backup
nix build --no-write-lock-file --out-link /var/lib/nixflix-gitops/bootstrap-result \
  "github:dales-garage/fateflix/$commit#nixosConfigurations.nixflix-production.config.system.build.toplevel"
test -e /var/lib/nixflix-gitops/bootstrap-result/etc/nixos/README.gitops
nix-env --profile /nix/var/nix/profiles/system --set /var/lib/nixflix-gitops/bootstrap-result
/var/lib/nixflix-gitops/bootstrap-result/bin/switch-to-configuration switch
# Remove the obsolete independent deployment entry point only after activation.
rm -f /etc/nixos/flake.nix /etc/nixos/flake.lock
cat > /etc/nixos/configuration.nix <<'NIX'
{ ... }: throw "Managed by Comin from dales-garage/fateflix main. See /etc/nixos/README.gitops and docs/gitops.md."
NIX
systemctl start comin
systemctl start nixflix-health
comin status
