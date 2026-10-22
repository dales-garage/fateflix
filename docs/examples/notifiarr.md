# Notifiarr

`nixflix.notifiarr` runs the native Notifiarr client as a dedicated dynamic user.
The official 0.9.7 binaries are pinned by SHA-256 for x86_64 and aarch64 Linux.

```nix
nixflix.notifiarr = {
  enable = true;
  apiKeyFile = "/run/secrets/notifiarr";
  settings.sonarr = [{
    name = "Sonarr";
    url = "http://127.0.0.1:8989";
    api_key = { _secret = "/run/secrets/sonarr"; };
  }];
};
```

`settings` follows the [official client configuration](https://github.com/Notifiarr/notifiarr/blob/v0.9.7/examples/notifiarr.conf.example).
Secrets are resolved at startup into a mode-0600 runtime configuration. Structured
sources support `format = "xml"`, `"json"`, `"yaml"`, or `"ini"` with a list of
keys in `key`. For XML, `key = [ "ApiKey" ]` reads an element and
`key = [ "@PlexOnlineToken" ]` reads an attribute. Missing or empty secrets prevent
the client from starting. Secret values never enter the Nix store.

The configuration is declarative: client UI configuration edits are replaced on
restart. Change the Nix settings and rebuild to persist changes. The generic
module binds to loopback by default and does not open the firewall.

## Personal host

`hosts/nixflix/notifiarr.nix` enables the client only in production. Its UI is
available on the LAN at `http://10.69.0.18:5454`; the firewall restricts access to
the existing server/client LANs. Sign in with the Notifiarr account as described
in the [upstream login instructions](https://notifiarr.wiki/pages/client/afterInstall/).

The client connects to both Sonarr and Radarr pairs, Lidarr, Prowlarr, Readarr
when enabled, SABnzbd, Plex, and Tautulli. It also checks TCP availability for
Seerr, both Bazarr instances, Whisparr, Audiobookshelf, Mylar3, Stash, and Homepage.
The latter checks report availability; they do not provide media event integration
for applications without a Notifiarr connector.

`notifiarr-connections.service` configures the built-in Notifiarr connections in
the eight Arr instances, the [Seerr webhook](https://notifiarr.wiki/pages/integrations/seerr/),
the [Bazarr JSON providers](https://notifiarr.wiki/pages/integrations/bazarr/), and
the [Plex account webhook](https://notifiarr.wiki/pages/client/afterInstall/#plex-webhook).
It preserves unrelated connections, updates existing Notifiarr entries, and stores
initial settings in `/var/lib/notifiarr-connections/*.before.json` with root-only
access. An already-enabled unrelated Seerr webhook or Bazarr JSON provider causes
that integration to fail instead of overwriting it. Disabled staging Apprise
settings are replaced when Notifiarr is enabled. The job does not run in staging.

Provision the key on `.18` as `marty`:

```sh
pass insert secretspec/nixflix/notifiarr/NOTIFIARR_API_KEY
nix run .#provision-notifiarr
```

The separate SecretSpec profile resolves the key and atomically installs it at
`/var/lib/nixflix-secrets/notifiarr-api-key`. After rotating a key, reprovision it
and restart both `notifiarr` and `notifiarr-connections`.

The deployment follows the repository's `migration/nixflix` bookmark workflow.
`/etc/nixos/flake.nix` pins the deployed GitHub commit, so
`sudo nixos-rebuild switch --flake /etc/nixos#nixflix` retains the module.
To run its provisioner independently of the remote checkout:

```sh
revision=$(cat /var/lib/nixflix-deploy/deployed)
nix run "github:declarative-dale/nixflix/$revision#provision-notifiarr"
```

The site controls integration triggers, Discord channels, client tunnels, and
scheduled actions. Configuring local connections does not select new channels or
enable TRaSH sync. Verify those choices on Notifiarr.com and check the client's
application connection tests after activation.

Run local checks with:

```sh
python3 -m unittest discover -s tests/migration -v
nix build .#checks.x86_64-linux.notifiarr-eval .#packages.x86_64-linux.notifiarr
```
