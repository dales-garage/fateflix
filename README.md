<p align="center">
  <img src="docs/assets/logo.svg" alt="Red NixFlix logo, reused to credit the upstream project" width="180" />
</p>

<h1 align="center">FateFlix</h1>
<p align="center">A downstream NixOS media appliance, built on NixFlix.</p>

FateFlix is an opinionated appliance flake that brings media services, storage,
download policy, playback, monitoring and deployment together as a complete
NixOS system. It consumes [NixFlix](https://github.com/kiriwalawren/nixflix) as a
pinned input and builds an operational media host on top of its declarative
service modules.

NixFlix provides the foundation: NixOS options and API-based configuration that
connect media applications such as Sonarr, Radarr, Prowlarr and Jellyfin.
FateFlix adds the host configuration and operating policy around those modules,
including runtime secrets, storage layout, processing jobs, health checks and
reviewed updates through Comin.

## How FateFlix uses NixFlix

The relationship is explicit in the flake inputs:

```nix
nixflix = {
  url = "github:kiriwalawren/nixflix";
  flake = false;
};
```

NixFlix is an input to FateFlix's flake, pinned by `flake.lock`. The
`flake = false` setting fetches upstream's source rather than evaluating its
flake outputs. FateFlix assembles that source with reviewed patches,
compatibility modules, plugin support and package definitions, then imports the
resulting NixOS modules into its own host composition.

| Layer | Responsibility |
| --- | --- |
| Upstream NixFlix | Declarative media-service options and application configuration |
| FateFlix integration | Pinned upstream source, patches, compatibility changes and module exports |
| FateFlix capabilities | Storage, secrets, media, downloads, playback, processing and monitoring policy |
| FateFlix appliance | Machine configuration, production/staging roles and production deployment |

See [the architecture guide](docs/fateflix.md) for composition and capability
ownership, and [the NixFlix integration](integrations/nixflix/README.md) for the
source assembly process.

## What the appliance adds

- **Host composition:** shared capabilities assembled with Den, flake-parts and
  import-tree, with separate production and staging roles.
- **Storage and download policy:** canonical media/download paths, capacity
  checks and explicit protocol restrictions.
- **Runtime secrets:** provisioning through SecretSpec, with separate production
  and staging namespaces.
- **Playback and processing:** acceleration settings, playback diagnostics,
  conversion and remux tooling.
- **Operations:** monitoring, persistent maintenance holds, backup/recovery
  procedures and optional FreeCORE NAS telemetry.
- **Reviewed updates:** Renovate, artifact generation and CI feed pull requests;
  Comin follows reviewed production changes on `main`.

## Explore or adapt FateFlix

Start with [Getting started](docs/getting-started/index.md). The preferred
production output is `nixosConfigurations.fateflix`; `nixflix` and
`nixflix-production` are retained aliases. `nixflix-staging` is an alternate
role of the same machine configuration, with production deployment disabled.

The checked-in appliance describes a specific machine and storage layout.
Adapt hardware, filesystem identities, networking, storage and secrets before
using it on another host. The staging output shares those machine definitions;
it is not a ready-made second machine.

FateFlix also exports `nixosModules.default` (alias `nixosModules.nixflix`) for
consuming its adapted NixFlix modules in your own NixOS configuration. Importing
that module gives you the service options; the complete appliance comes from
FateFlix's host and capability composition.

## Documentation

- [Getting started](docs/getting-started/index.md): inspect the appliance or use
  its adapted modules on your own host.
- [Architecture and configuration](docs/fateflix.md): inputs, capability
  ownership, host roles and settings.
- [GitOps and updates](docs/gitops.md): production deployment and recovery.
- [Operations](docs/operations.md): playback, storage and maintenance.
- [Dependency updates](docs/dependency-updates.md): Renovate and supplemental
  dependency ownership.
- [Migration runbook](docs/migration/nixflix.md): deployment history and detailed
  operator procedures.

The [upstream NixFlix documentation](https://kiriwalawren.github.io/nixflix/)
explains the original project's modules and configuration. FateFlix's docs
cover the downstream appliance and its adaptations.

## Development

```sh
nix develop
nix fmt
nix build --no-link .#lib.nixflixSource
nix flake check --no-build
```

The adapted source must be realized before evaluation; see the architecture
guide for builder requirements and the full validation procedure.
`nix flake check --no-build` evaluates checks; `nix flake check` also builds them.

## Upstream credit and license

FateFlix builds on [NixFlix by Kiri Walawren](https://github.com/kiriwalawren/nixflix)
and reuses its red logo. Upstream's work remains the foundation for the media
configuration. This repository is licensed under [MPL 2.0](LICENSE).
