---
title: FateFlix
---

# FateFlix

<p align="center">
  <img src="assets/logo.svg" alt="Red NixFlix logo, reused from upstream" width="160" />
</p>

FateFlix is a downstream NixOS appliance flake built on
[NixFlix](https://github.com/kiriwalawren/nixflix). It consumes pinned upstream
source as a flake input, adapts its media-service modules and composes them with
host configuration, storage, runtime secrets, playback, processing, monitoring
and production deployment.

NixFlix supplies the declarative media configuration. FateFlix turns that
foundation into an opinionated system with its own operating policy and update
workflow. The input is declared with `flake = false`, so FateFlix imports modules
from an assembled source tree rather than consuming upstream flake outputs.

## Choose a starting point

- **Explore or adapt the appliance:** begin with [Getting started](getting-started/index.md).
- **Understand the composition:** read [Architecture and configuration](fateflix.md).
- **Operate the existing appliance:** use [GitOps and updates](gitops.md) and
  [Operations](operations.md).
- **Configure individual applications:** use the module examples and
  [option reference](reference/index.md). These document the service module
  interface; the appliance's capability composition supplies its host policy.

## Upstream and downstream

| NixFlix provides | FateFlix builds on top |
| --- | --- |
| Media-service options and API-based configuration | A composed NixOS host with production/staging roles |
| Application integrations | Storage, secrets, download and playback policy |
| Upstream source releases | Locked inputs, compatibility changes and reviewed dependency updates |

The appliance's checked-in hardware and filesystem definitions belong to an
existing machine. Adapt those definitions before deploying elsewhere. See
[Getting started](getting-started/index.md) for the difference between the
complete appliance and the reusable module exports.

The red logo is reused from upstream NixFlix. For the original project's setup
and service documentation, visit the
[upstream documentation](https://kiriwalawren.github.io/nixflix/).
