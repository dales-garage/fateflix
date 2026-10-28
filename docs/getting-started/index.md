---
title: Getting Started
---

# Getting started with FateFlix

FateFlix offers a complete downstream appliance and reusable adapted NixFlix
modules. Choose the appliance when working on this repository's host
composition, or the module export when adding media services to a NixOS host
you already maintain.

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
`nixflix-staging` selects a staging role with separate secrets and no production
Comin deployment. It shares the existing machine's hardware definitions.

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

## Use the adapted modules on your own host

Add FateFlix as an input to your own flake, then import its module export:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    fateflix.url = "github:dales-garage/fateflix";
  };

  outputs = { nixpkgs, fateflix, ... }: {
    nixosConfigurations.my-media-host = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        ./configuration.nix
        fateflix.nixosModules.default
      ];
    };
  };
}
```

Your `configuration.nix` supplies the machine configuration and selects services
through `nixflix.*` options. The import exposes FateFlix's adapted NixFlix module
interface; it does not import the appliance's host profile, storage choices or
Comin deployment.

See the [basic module example](../examples/basic-setup.md) and
[options reference](../reference/index.md) for service configuration. Application
API credentials must use runtime secret paths rather than literal values in Nix.
For unadapted upstream NixFlix, follow the
[upstream installation guide](https://kiriwalawren.github.io/nixflix/getting-started/).

## How the dependency is consumed

FateFlix declares `inputs.nixflix` with the upstream GitHub URL and
`flake = false`. `flake.lock` pins the source revision. The integration assembles
that source with local patches and overlays before exposing its NixOS modules.

See [Architecture and configuration](../fateflix.md#how-nixflix-becomes-the-appliance)
for the path from upstream input to appliance output, and
[Dependency updates](../dependency-updates.md) for how changes are reviewed.
