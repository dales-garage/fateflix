# Homepage dashboard

`nixflix.homepage` wraps the native NixOS Homepage service with Nixflix proxy
integration and runtime API credentials. It is opt-in; the `.18` production host
enables it in `hosts/nixflix/homepage.nix`. The staging host leaves it disabled.

The host configuration includes all 17 media applications, grouped into Watch &
Listen, Movies & TV, Downloads & Subtitles, Books & Music, and Adult. Sonarr,
Sonarr 4K, Radarr, Radarr 4K, Prowlarr, Lidarr and SABnzbd have API widgets. Other
cards have links and HTTP response checks. The resource widget shows VM CPU,
memory and root filesystem usage, not NAS capacity.

## Addresses and deployment

After deploying the host configuration, use `http://10.69.0.18:8082/`.
`https://homepage.vm.internal/` additionally requires applying the existing router
DNS and HTTPS configuration from the updated `local-services.json` manifest.
The manifest creates the VM Caddy HTTP origin as well. Homepage is absent from
the public service allowlist, and its direct port follows the same two LAN
firewall rules as the other private applications.

Creating these files does not deploy the VM or router. Use the host's normal
build/test/switch workflow and the router apps documented in
[migration operations](../migration/nixflix.md#https-dns-and-remote-access).
The internal HTTPS name requires trusting the router's public CA certificate.

Homepage 1.12.3, pinned by this host's Nixpkgs, has no built-in login. The dashboard
and its API metrics are intended for the trusted LAN. An allowed Host header is
not user authentication. Add proxy authentication before any future public route.

## Customize this host

```nix
{
  nixflixHost.homepage = {
    apiWidgets = true;
    useInternalNames = true; # false uses direct IP:port links
    showAdultServices = true;
  };
  nixflix.homepage.settings.title = lib.mkForce "My Media";
}
```

Ports and hostnames come from `hosts/nixflix/local-services.json`. Edit that
manifest to change the host's Homepage port, keeping the firewall and router
configuration consistent. Customize the cards in `hosts/nixflix/homepage.nix`;
use `lib.mkAfter` to append groups or `lib.mkForce` to replace them. Turning off
`apiWidgets` keeps every link and HTTP monitor and removes the credential loads.

## Reuse the module

```nix
{
  nixflix.enable = true;
  nixflix.homepage = {
    enable = true;
    # Loopback binding and closed firewall are the defaults.
    reverseProxy.expose = true; # use a proxy with appropriate access controls
    settings = {
      title = "Media";
      theme = "dark";
      color = "slate";
    };
    apiKeyFiles.SONARR = "/run/secrets/sonarr-api-key";
    services = [
      {
        TV = [
          {
            Sonarr = {
              href = "https://sonarr.example.internal/";
              siteMonitor = "http://127.0.0.1:8989/";
              widget = {
                type = "sonarr";
                url = "http://127.0.0.1:8989";
                key = "{{HOMEPAGE_FILE_SONARR}}";
              };
            };
          }
        ];
      }
    ];
  };
}
```

`apiKeyFiles` values are absolute **strings naming files on the deployed host**.
Do not use `builtins.readFile` or literal API keys. Systemd loads the files into
the service's private credential directory; Homepage reads them through its
`HOMEPAGE_FILE_*` substitution. The generated YAML contains placeholders only.
No container socket or access to entire application state directories is needed.
Restart `homepage-dashboard.service` after rotating credentials.

`services`, `settings`, `widgets`, `bookmarks`, `customCSS`, `environmentFiles`,
`allowedHosts`, `listenAddress`, `listenPort`, and `openFirewall` are configurable
under `nixflix.homepage`. Native service options, including package overrides,
remain available under `services.homepage-dashboard`.

See [Homepage service configuration](https://gethomepage.dev/configs/services/)
and the [pinned version's secret substitution documentation](https://github.com/gethomepage/homepage/blob/v1.12.3/docs/installation/docker.md#using-environment-secrets).
