---
title: Appliance Configuration
---

# Appliance configuration

FateFlix is configured as a complete appliance. To make a change, start with
[`modules/profiles/media-server.nix`](https://github.com/dales-garage/fateflix/blob/main/modules/profiles/media-server.nix)
and the [architecture guide](../fateflix.md). Edit machine settings under
`hosts/nixflix/` or service policy under the capability that owns it. See the
[option reference](../reference/index.md) for service settings.

From your development checkout, run:

```sh
nix develop -c just check
nix develop -c just build
```

This evaluates and builds without activating. For limited development testing,
`nix develop -c just build-staging` builds the staging role. Only reviewed
`main` deploys to the production appliance through Comin.

If you need standalone media modules on another NixOS machine, follow the
[upstream NixFlix installation guide](https://kiriwalawren.github.io/nixflix/getting-started/).
