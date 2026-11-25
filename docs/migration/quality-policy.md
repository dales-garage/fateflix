# Quality policy for nixflix

The existing HD profiles now prefer AV1 in MP4, then AV1 in other containers,
H.265/HEVC, H.264/AVC, and other codecs. This applies to Sonarr HD and Radarr HD;
the 4K and SD tier designs below remain proposals. No library assignments or
searches are changed, and the Recyclarr timer remains inactive.

The live HD profiles retain their existing resolution/source ordering and quality
rejections. Custom-format scores decide codec preference within those quality
tiers. AV1 scores 3000, HEVC 2000, AVC 1000, and AV1 with an MP4 release-title
marker earns an additional 500. Existing positive secondary preferences are
rescaled to a total below 500 so they cannot reverse that order or offset the
existing -10000 rejection scores. The minimum score is 0 to retain fallbacks;
the upgrade target is 3500, reached by an identified AV1 MP4 release.

The policy is declared in `capabilities/media/hd-codec-policy.json` and applied by
`scripts/nixflix_hd_profiles.py`. Recyclarr's pre-start hook adds profile-specific
guide score overrides and preserves the two local formats; its post-start hook
restores their definitions and scores. The helper is idempotent and targets only
the named HD profiles. On the current VM, the same hooks are installed in
`/etc/systemd/system.control/recyclarr.service.d/90-fateflix-hd-codecs.conf` so they
survive reboot before the next Nix deployment. No recurring sync was enabled.

MP4 detection before download depends on the release title identifying the
container. An AV1 release without an MP4 marker still receives the AV1 score;
these rules do not inspect remote payloads or transcode files.

## Tool choice

Keep **Recyclarr** for this TRaSH-first stack. Nixflix already integrates it with
both Sonarr and both Radarr instances, and this host pins the TRaSH guides and
Recyclarr templates in `flake.lock`. Recyclarr supports profile-specific scores,
quality ordering, size definitions and custom resource providers, which cover
the requested exceptions without introducing another configuration owner.

Profilarr is useful when interactive profile editing, release testing and a web
UI are the priority. Configarr is another configuration-driven option with
custom formats and Recyclarr-template support. Neither is needed merely to add
these codec and size rules. Only one tool should manage a given profile's scores.

## Three tiers

| Profile | Sources and resolution | Codecs | Initial maximum size budget |
| --- | --- | --- | --- |
| Efficient 4K | 2160p WEB-DL / WEBRip | Require recognized H.265/HEVC or AV1; H.265 is the more widely available starting point | 120 MB/min, about 14.4 GB for a two-hour movie |
| Efficient HD | Existing HD quality/source groups | Prefer AV1 MP4, AV1, H.265, H.264, then other codecs | Existing limits retained; no new cap applied |
| Legacy SD | Native SD WEB, DVD encodes or SDTV, typically 480p/576p | Prefer H.264 when available; allow older MPEG-4/Xvid and MPEG-2 releases for availability | 18 MB/min, about 400 MB for a 22-minute episode |

These are proposed starting **caps**, not minimum targets or TRaSH defaults.
Size limits should scale with runtime. Use separate lower minimum/preferred
values, with relaxed SD minimums so small animation releases are not rejected.
Review actual availability before enforcing these limits across the library.

For a future HD source-group redesign, put every acceptable 1080p source above the 720p group. A profile can
accept 720p now and upgrade later when an acceptable 1080p release appears.
It cannot prove that a 1080p release will never become available. A delay profile
can give preferred releases time to appear before downloading the fallback.

Assign Legacy SD explicitly to older series; do not infer it solely from release
year or animation genre. Some older shows have real HD restorations. Sailor Moon
may also need anime-specific release-group and language choices, while Johnny
Bravo does not need those anime defaults. Use a profile in the existing standard
Sonarr instance; a third server instance is unnecessary.

## TRaSH adjustments required

The pinned guides score AV1 and HD x265 at **-10000** by default. The applied HD
policy explicitly overrides those scores. The 4K profiles have not been changed;
review their `AV1` and `x265 (no HDR/DV)` rules before applying the proposed 4K
policy so a codec preference does not accidentally reject a reasonable SDR encode.

For a future strict-codec profile, use a profile-specific rejection rule for codecs outside the allowed set.
A positive H.265 or H.264 score alone is a preference, not a strict requirement,
and other positive TRaSH scores can offset a weak penalty. Test the complete
score combinations, including AV1, HEVC, AVC and releases with no codec marker.
Codec identification at grab time relies largely on release metadata/names and
cannot guarantee the contents of a download.

Exclude Remux qualities, BR-DISK, full disc/ISO releases and raw/lossless video.
The proposed WEB-only UHD source list also avoids Blu-ray encodes by default.
An encoded BDRip is different from a full disc or remux; allowing compact Blu-ray
encodes later is a separate choice, still subject to the same size cap.
Remuxes retain the original compressed disc streams; they are not generally
uncompressed video, but are often much larger than the desired encodes.

MP4 and MKV are containers, not quality levels or codecs. Allow both; an MKV can
contain the same compact H.264 stream as an MP4. Avoid requiring MP4 for rare
older shows. Recyclarr/Sonarr/Radarr select releases; they do not transcode them
or convert containers. AV1 direct playback also depends on the viewing device.

Before enabling recurring sync, preview the changes, test representative release
names and sizes, assign the new profiles deliberately, and update Seerr's default
profile selections. Existing files do not become smaller merely by changing a
quality profile.

## References

- [Recyclarr quality profiles](https://recyclarr.dev/reference/configuration/quality-profiles/)
- [Recyclarr custom formats](https://recyclarr.dev/reference/configuration/custom-formats/)
- [Recyclarr custom resource providers](https://recyclarr.dev/reference/settings/resource-providers/configuration/)
- [TRaSH Radarr AV1 definition](https://github.com/TRaSH-Guides/Guides/blob/master/docs/json/radarr/cf/av1.json)
- [TRaSH Sonarr AV1 definition](https://github.com/TRaSH-Guides/Guides/blob/master/docs/json/sonarr/cf/av1.json)
- [Profilarr](https://github.com/Dictionarry-Hub/profilarr)
- [Configarr](https://github.com/raydak-labs/configarr)
