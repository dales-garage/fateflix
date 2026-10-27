# NixFlix integration

`default.nix` assembles the source-only IFD from the upstream revision pinned in
`flake.lock`, in this order:

1. Apply `patches/` to the fetched upstream source.
1. Overlay verbatim `vendor/modules/` files, documented by their provenance.
1. Overlay maintained `compatibility/` modules at their upstream module paths.
1. Overlay `plugins/jellyfin/` and `plugins/navidrome/` into their module trees.
1. Overlay the repository's `pkgs/` definitions.

The assembled paths preserve relative imports expected by upstream modules.
The repository directories are not independently imported as NixOS modules.
`modules/integrations/nixflix.nix` owns the public module exports and the
`nixflix-api` Den aspect. This aspect supplies upstream declarations without
activating the media service stack.

`plugins/` owns maintained manifests, generated definitions and updater scripts.
The plugin update allowlists, Renovate configuration and CI planner use these
source locations. Changing the assembly, vendor sources or compatibility code
selects the full integration suite.
