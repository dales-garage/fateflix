# FreeCORE alerts to the existing Discord errors channel

This adds FreeCORE's native warning/error feed to the existing Notifiarr account.
It needs no NAS API credential: a scheduled task on FreeCORE reads the local
middleware API through its native Python client in a bounded child process. The NixFlix change adds independent TCP checks for NAS SMB and
HTTPS. The existing Discord channel and bot configuration remain in use.

## 1. Copy the Passthrough webhook and channel ID

In Notifiarr.com, enable **Passthrough** and copy the webhook URL from its basic
instructions. This is the integration URL, not the local client UI URL or an Arr
webhook. A separate integration key is preferable to reusing a global key.

In Discord, enable **User Settings > Advanced > Developer Mode**, then right-click
the existing errors channel and **Copy Channel ID**. You need the numeric ID,
not the channel name. Keep the webhook URL private.

## 2. Install the bridge on FreeCORE

Open FreeCORE's administrator Shell. Choose an unshared directory on a persistent
pool; replace `POOL` below with the real pool name. `zpool list` can show the names.
Keep the script, configuration and state together so they survive reboot.

After the reviewed PR is merged, run:

```sh
NAS_ALERT_DIR=/mnt/POOL/monitoring/notifiarr
install -d -m 700 "$NAS_ALERT_DIR"
fetch -o "$NAS_ALERT_DIR/freecore-notifiarr.py" \
  https://raw.githubusercontent.com/declarative-dale/nixflix/main/scripts/freecore-notifiarr.py
chmod 700 "$NAS_ALERT_DIR/freecore-notifiarr.py"
/usr/local/bin/python3 "$NAS_ALERT_DIR/freecore-notifiarr.py" init
```

The installer prompts for the webhook URL with hidden input, then the errors
channel ID. It saves `notifiarr.json` with mode 0600; do not put the webhook into
a shell argument, environment variable, Nix expression or cron command.

Send a single labelled test, then check the existing errors channel:

```sh
/usr/local/bin/python3 "$NAS_ALERT_DIR/freecore-notifiarr.py" test
```

The test confirms delivery only; it does not simulate a real disk failure. Run
one real poll next. This sends any current, non-dismissed WARNING-or-higher
alerts, at most four deliveries per invocation:

```sh
/usr/local/bin/python3 "$NAS_ALERT_DIR/freecore-notifiarr.py" run
/usr/local/bin/python3 "$NAS_ALERT_DIR/freecore-notifiarr.py" status
```

## 3. Schedule it

In **Tasks > Cron Jobs > Add**:

| Setting | Value |
| --- | --- |
| Description | FreeCORE alerts to Notifiarr |
| Command | `/usr/local/bin/python3 /mnt/POOL/monitoring/notifiarr/freecore-notifiarr.py run` |
| User | `root` |
| Schedule | Every minute: `* * * * *` |
| Enabled | Yes |
| Hide Standard Output | Yes |
| Hide Standard Error | No |

Replace `POOL` in the command too. Use **Run Now**, then run `status` from the
Shell. `last_poll` should advance each minute and `pending` should return to zero
as Notifiarr acknowledges deliveries. Cron errors remain visible for diagnosis.

The bridge validates the complete feed and waits for `system.ready` before
inferring that an alert cleared. A feed failure preserves existing alerts and
can still flush previously queued deliveries. Dismissing an alert does not
generate a recovery. A recovery means FreeCORE no longer reports the alert;
it is not independent proof that a physical fault was repaired.

Configuration, active IDs and delivery outbox are private. State is atomically
replaced and synced before sending. Failed deliveries retain their event IDs for
retry; Passthrough requests reuse those IDs with `update=true`. A crash between
remote acknowledgement and local checkpoint can retry an event. Up to four
ten-second HTTP calls follow bounded local API queries, and a nonblocking lock
prevents overlapping cron workers. State corruption or a full outbox fails
without resetting/dropping existing state. Preserve the private files for review
instead of deleting them to clear a failure.

## 4. Enable the NAS health sources

Under **Services**, enable **S.M.A.R.T.** and automatic startup. Under
**Tasks > S.M.A.R.T. Tests**, verify the physical drives have test schedules.
If none exist, add short and long schedules appropriate to the drives; avoid
overlapping tests with pool scrubs or resilvers. Keep existing working schedules.
Review pool scrub tasks as well. FreeCORE's middleware generates the disk, pool,
boot-pool, UPS and hardware alerts that the bridge forwards when those sources
are available; the bridge does not run SMART tests or scrub/modify pools.

In **System > Alert Settings**, keep important disk/pool/hardware alerts enabled
and choose immediate frequency. The bridge polls the current alert feed at its
own one-minute frequency, independently of native alert-service schedules. An
alert configured as **Never** can be excluded from that feed. You do not need
to add a Slack/Mail alert service for this bridge.

Physical SMART data requires direct disks/HBA passthrough or appropriate host
monitoring when FreeCORE is virtualized; a virtual disk or SMB mount cannot
provide the physical drive's complete health.

## 5. Check independent availability alerts

After the NixFlix PR is deployed, the Notifiarr client at
`http://10.69.0.18:5454` shows **FreeCORE SMB** (`10.69.0.10:445`) and **FreeCORE
Web** (`10.69.0.10:443`) under Services/Monitoring. Both run each minute with a
five-second timeout. They use the existing **Network integration** channel on
Notifiarr.com; confirm it is the errors channel and includes recovery events.
The TCP checks report listeners, while the existing NAS probe checks access to
the mounted share and the bridge carries detailed FreeCORE alerts.

Changes made directly in the NixFlix client UI are replaced on restart; these
two checks live in `hosts/nixflix/notifiarr.nix`. If NixFlix and FreeCORE share an
XCP-ng host, a whole-host outage takes down both the NAS and these local checks.
Detecting that case requires a monitor outside that host.

References: [FreeCORE alerts](https://docs.freecore.org/tutorials/system/creating-alerts/),
[SMART tests](https://docs.freecore.org/tutorials/tasks/running-smart-tests/),
[Notifiarr Passthrough](https://notifiarr.wiki/pages/integrations/passthrough/),
[Notifiarr health checks](https://notifiarr.wiki/pages/client/healthChecks/).
