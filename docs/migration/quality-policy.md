# Proposed quality policy for nixflix

This is a profile design, not an applied configuration. The Homepage change does
not change existing profiles, assign libraries to new profiles, trigger searches,
or enable the currently inactive Recyclarr timer.

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
| Compatible HD | 1080p WEB-DL / WEBRip, then 720p WEB-DL / WEBRip / HDTV | Require recognized H.264/AVC | 40 MB/min for 1080p (about 4.8 GB / two hours); 25 MB/min for 720p (about 3 GB / two hours) |
| Legacy SD | Native SD WEB, DVD encodes or SDTV, typically 480p/576p | Prefer H.264 when available; allow older MPEG-4/Xvid and MPEG-2 releases for availability | 18 MB/min, about 400 MB for a 22-minute episode |

These are proposed starting **caps**, not minimum targets or TRaSH defaults.
Size limits should scale with runtime. Use separate lower minimum/preferred
values, with relaxed SD minimums so small animation releases are not rejected.
Review actual availability before enforcing these limits across the library.

For HD, put every acceptable 1080p source above the 720p group. A profile can
accept 720p now and upgrade later when an acceptable 1080p release appears.
It cannot prove that a 1080p release will never become available. A delay profile
can give preferred releases time to appear before downloading the fallback.

Assign Legacy SD explicitly to older series; do not infer it solely from release
year or animation genre. Some older shows have real HD restorations. Sailor Moon
may also need anime-specific release-group and language choices, while Johnny
Bravo does not need those anime defaults. Use a profile in the existing standard
Sonarr instance; a third server instance is unnecessary.

## TRaSH adjustments required

The pinned guides currently score AV1 at **-10000** in their default unwanted
formats. AV1 must be explicitly allowed in the 4K profile, while keeping it
rejected for the H.264-only HD profile. Review the `x265 (HD)` and `x265 (no HDR/DV)`
rules per profile too; a codec preference should not inadvertently reject a
reasonable SDR 4K encode.

Use a profile-specific rejection rule for codecs outside the allowed set.
A positive H.265 or H.264 score alone is a preference, not a strict requirement,
and other positive TRaSH scores can offset a weak penalty. Test the complete
score combinations, including AV1, HEVC, AVC and releases with no codec marker.
Codec identification at grab time relies largely on release metadata/names and
cannot guarantee the contents of a download.

Exclude Remux qualities, BR-DISK, full disc/ISO releases and raw/lossless video.
The WEB-only HD/UHD source lists above also avoid Blu-ray encodes by default.
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
