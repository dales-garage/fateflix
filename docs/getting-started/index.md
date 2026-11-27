---
title: Getting Started
---

# Getting started with FateFlix

FateFlix is a complete downstream appliance. Its adapted service modules are
internal to the appliance. For standalone service modules, use the
[upstream NixFlix installation guide](https://kiriwalawren.github.io/nixflix/getting-started/).

## Inspect the appliance

Use a machine with Nix and flakes enabled. The adapted upstream source is built
for `x86_64-linux`; evaluation needs a builder for that system.

```sh
git clone https://github.com/dales-garage/fateflix.git
cd fateflix
nix develop
nix build --no-link .#lib.nixflixSource
nix eval .#nixosConfigurations.fateflix.config.system.build.toplevel.drvPath
```

These commands fetch dependencies and evaluate the production system without
activating it. To build its closure:

```sh
nix build --no-link .#nixosConfigurations.fateflix.config.system.build.toplevel
```

`fateflix`, `nixflix` and `nixflix-production` name the same production system.
`nixflix-staging` is for limited development testing from a test checkout.
It uses separate secrets and does not run Comin. It shares the existing machine's
hardware definitions; it is not a separate VM or a production deployment target.
Use `nix develop -c just build-staging` to build it without activating it.

## Adapt the appliance to another machine

The checked-in hosts are specific to the existing appliance. Before activation,
review these sources together:

| Source | What to adapt |
| --- | --- |
| `hosts/nixflix/` | Hardware, filesystem identities, networking, storage and local endpoints |
| `modules/hosts/` | Host declarations and production/staging role selection |
| `modules/profiles/media-server.nix` | Capability selection and shared host policy |
| `capabilities/` | Storage, download, playback, processing, monitoring and secrets settings |

Use [Architecture and configuration](../fateflix.md) to understand the capability
composition and canonical options. Provision credentials through the
[documented runtime secrets workflow](../fateflix.md#runtime-secrets). A separate
staging machine needs its own hardware definitions.

For the existing production appliance, follow [GitOps and updates](../gitops.md).
Comin owns activation from reviewed `main`; local evaluation and builds are
separate from deployment.

## How the dependency is consumed

FateFlix declares `inputs.nixflix` as a full flake input tracking
`github:kiriwalawren/nixflix/main`. `flake.lock` pins the revision, and
`nix flake update nixflix` refreshes it from upstream main. Shared dependencies
follow FateFlix inputs. The integration assembles its `outPath` with local
patches and overlays before composing the appliance.

See [Architecture and configuration](../fateflix.md#how-nixflix-becomes-the-appliance)
for the path from upstream input to appliance output, and
[Dependency updates](../dependency-updates.md) for how changes are reviewed.
