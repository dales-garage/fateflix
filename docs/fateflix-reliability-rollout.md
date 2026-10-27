# FateFlix reliability investigation and rollout

On 2026-10-26, production was running Comin commit `913b56a` and system
`s949ncqq5xvyxfn7fraz66yw53azl7nr-nixos-system-nixflix-26.05.20261021.da6dc0e`.
The VM had stayed up since 2026-10-24 00:31 CDT. No units were currently failed,
and current boot application restart counters were zero. The NAS had about
1.1 TiB free (95% used); its capacity threshold report was still `ok`.

Three-day journal analysis found:

- Local application cold starts caused earlier notification reconciliation
  failures. Production already had the bounded startup retry and supported
  Bazarr Python fixes; FateFlix needed those changes and the current package pins.
- Plex account-webhook failures on October 25 at 01:35 and October 26 at 16:54 CDT
  failed the combined notification unit. Local media checks remained healthy,
  while that unit caused false overall health failures until the next retry.
- Six NAS health failures coincided with probe publication. Completed snapshots
  one to six seconds later reported fresh accessible NAS results. The probe
  cleared NAS status during every root-first publication, creating a race.
- Historical Plex/Stash restart failures preceded the current stable boot.
  Recent kernel logs showed no OOM kills or CIFS transport errors. Plex also
  reported malformed media headers and analysis/transcode failures; those do
  not establish a service-configuration fault and do not authorize media repair.

The fixes retain the original expiry of carried NAS samples and isolate Plex
cloud reconciliation in a separate, observable unit. Genuine mount, credential,
local application and permanent authentication failures remain failures.

The rollout must compare the candidate with the current production package and
identity contract, build and evaluate both outputs, run regressions and canaries,
and pass required CI before merging. Comin remains the activation owner. Record
the prior generation and protected state backups, then verify authenticated
local APIs, mounts, notifications, proxy routes, playback diagnostics and several
scheduled probe/reconciliation cycles after activation. Keep the known-good
generation available for rollback. A production rollout does not validate a
separate staging machine or staging rollback.
