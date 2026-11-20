# Changelog

All notable changes to this integration. Dates are release dates.

## v1.3.0+benjagit.11 — fork: a resting proxy hands over to Home Assistant

- When a thermostat's best scanner is resting after 8 failures, Home Assistant
  chooses. Before, the next-best scanner was forced even with a record like
  0 of 48, and was then rested in turn.

## v1.3.0+benjagit.10 — fork: parallel connections, proxy on the dashboard

- Connections are now serialized per scanner instead of for the whole home, so
  different proxies read thermostats at the same time. One proxy still handles
  one thermostat at a time.
- A connect left to Home Assistant goes through the scanner with the strongest
  signal, so it can queue behind that scanner's other connects.
- New sensor **Bluetooth proxy**: the scanner the thermostat is assigned to
  right now, with `assigned_by` (`learned`, `locked` or `ha`).
- New select **Preferred proxy**: lock a thermostat to a scanner from a
  dashboard. Same setting as the option; it applies without reloading the
  entry.
- The connection sensor also shows `assigned_proxy` and `assigned_by`.

## v1.3.0+benjagit.9 — fork: fairer connect counting

- A connect is counted once per scanner. The built-in retry was counted as a
  second failure, although the proxy refuses it without trying.
- A scanner is rested after 8 failed connects in a row instead of 3. Three in a
  row are ordinary for these valves, so the best proxy was rested needlessly.

## v1.3.0+benjagit.8 — fork: preferred proxy

- Each thermostat now connects through the Bluetooth proxy that works best for
  it. Successful and failed connects are counted per scanner, and the scanner
  with the best record is used when it has heard the thermostat within 10
  minutes. About 1 connect in 10 is left to Home Assistant, so the counts of
  the other scanners stay current. Before this, Home Assistant chose by signal
  strength alone.
- New option **Preferred Bluetooth proxy**: lock a thermostat to one scanner.
  The lock overrides the learned choice.
- A scanner that fails 3 connects in a row (8 from benjagit.9) is rested for 30
  minutes. If the
  chosen scanner is resting, has no free slot or has not heard the thermostat,
  Home Assistant chooses as before.
- The connection sensor has new attributes: `proxy`, `proxy_choice` (`learned`,
  `locked` or `ha`), `preferred_proxy` and `proxy_stats` (attempts and
  successes per scanner).
- The cache is written when an entry unloads, so changing options no longer
  drops the last few seconds of state.

## v1.3.0+benjagit.7 — fork: connection sensor follows every retry

- The connection sensor's attributes (consecutive_failures, last_error,
  last_advertisement) now update on every failed retry. Home Assistant only
  refreshed entities on the first failure in a row, so a thermostat that
  failed six times still showed one failure and the first error.

## v1.3.0+benjagit.6 — fork: E10 clears on the syncing poll

- The error register is read back in the same connection after it is
  written, like temperature, settings and time already were. After a clock
  sync, E10 now disappears at once instead of on the next poll.

## v1.3.0+benjagit.5 — fork: clock sync clears E10

- Every clock sync (automatic, the *Sync time* button or
  `danfoss_eco.sync_time`) now also clears `E10 invalid time`. The thermostat
  keeps the flag after a battery swap even with a correct clock; the official
  app clears it by writing the error register right after the time, and the
  integration now does the same. Only E10 is cleared: E9, E14 and E15 are
  written back as the device reported them.
- PROTOCOL.md: the error characteristic is writable; adds `10020002` and the
  language characteristic `1002000a`.

## v1.3.0+benjagit.4 — fork: startup no longer waits for the thermostats

- Setup no longer waits for the first Bluetooth poll. All thermostats share
  one connection lock, so with many of them Home Assistant stayed in
  "starting" until its 300 s timeout. Entities now come up on the cached
  reading, and the first poll runs in the background once Home Assistant
  has started.

## v1.3.0+benjagit.3 — fork: signal from the connecting proxy

- The Bluetooth signal sensor (and its `source` attribute) now only uses
  scanners that can connect. A passive gateway (e.g. Shelly BLU) no longer
  sets the value, so it reflects the link every poll actually uses.

## v1.3.0+benjagit.2 — fork: pairing keeps the key

- Pairing no longer fails with "Unknown error" after the key was read. The valve
  often refuses the follow-up connection used to read its name; that now falls
  back to the default title instead of discarding the key.

## v1.3.0+benjagit.1 — fork: upstream fixes not yet merged

Fork of deltasystems-pl/danfoss-eco-ha carrying two open upstream PRs by Lars Ryssel:

- #2 Device clock: write UTC epoch + standard offset like the official app. Before
  this, the weekly schedule ran 3 h early in Europe/Copenhagen summer time, and the
  automatic time sync overwrote clocks set by the Danfoss app.
- #3 Drop the cached BLE service table when a characteristic is missing, so a stale
  cache no longer stops polling until Home Assistant restarts.

## v1.3.0 — offline resilience

Radiator valves are weak-signal, deep-sleeping BLE devices. A proxy that is busy
(an ESPHome build pegging its CPU), a valve that drifts out of range, or a Home
Assistant restart used to blank the whole device and throw away whatever the user
had just asked for. That is now handled:

- **Cached readings.** A failed poll no longer makes the device *unavailable*.
  The last successful reading stays on show for `Keep the last reading for`
  hours (default 24, `0` = forever), and `Last poll` tells you how old it is.
  The cache is written to `.storage/danfoss_eco.<entry_id>` and restored on
  startup, so a restart no longer blanks the dashboard either.
- **Queued commands.** Setting a temperature (or a mode, config switch, comfort/
  setback temperature or weekly program) while the thermostat is out of reach no
  longer fails — the change is coalesced into a persistent queue, shown
  immediately on the entity, and written the moment the device is next reachable.
  Undelivered commands expire after `Keep undelivered commands for` hours
  (default 24, `0` = forever).
- **Faster recovery.** A failed poll is retried after 1, 2, 5, 10 then 15 minutes
  instead of waiting out the whole poll interval, and an advertisement from the
  thermostat triggers an immediate retry — so a valve that comes back within
  range of a proxy is picked up straight away.
- **New entities:** *Connection* (binary sensor — whether the radio link is
  actually up, with last success / last advertisement / last error attributes),
  *Pending commands* (sensor — count, with a readable list of what is queued),
  and *Discard pending commands* (button). The climate entity gained `cached`,
  `pending_writes`, `last_poll` and `pending_target_temperature` attributes.
- **One connection per cycle.** Queued writes are flushed inside the polling
  connection and applied to the settings block the device holds *right now*, then
  read back for confirmation — no separate radio wake-up per command.
- **Connections are serialized across all thermostats.** Three valves dialling
  one proxy at once is the quickest way to produce *"no backend with an available
  connection slot"*.
- Fix: a device that keeps the `E10 invalid time` flag raised even after its clock
  has been written correctly (seen on real hardware) no longer queues a clock sync
  on every single poll — E10 alone now triggers at most one resync per day.

## v1.2.4
- Fix `Handler DanfossEcoConfigFlow doesn't support step no_devices` crash when
  opening the setup flow while nothing was being advertised (missing
  `async_step_no_devices` handler for the "no thermostat detected" menu).

## v1.2.3 — important
- Fix a `NameError` that broke **every** polling cycle since v1.0.3: `read_state`
  referenced the schedule characteristic UUIDs without importing them, so no
  device ever populated its data (entities stuck *unavailable* regardless of
  signal). Added `pyflakes` to the pre-release checks to catch this class of bug.

## v1.2.2
- Keep the guided (button-press) pairing wizard as the primary path. When nothing
  is advertising, the flow now offers "Search again" / "Add manually (advanced)"
  instead of dropping straight into manual entry.

## v1.2.1
- Setup no longer blocks on the first poll: entities are created immediately
  (shown *unavailable* until a poll succeeds) so the device page and the
  **Refresh now** button are always available even for an out-of-range device.
- The Refresh now button stays pressable while polls are failing.

## v1.2.0
- Add a **Refresh now** diagnostic button to force an immediate read.

## v1.1.0
- **Reconfigure** flow: update a device's secret key / PIN from the UI.
- **Diagnostics** download (secret key and address redacted).
- Read the weekly schedule within the same BLE connection as the rest of the
  state — one radio wake per poll instead of two.
- `PARALLEL_UPDATES = 1` to serialize commands.

## v1.0.3
- **Manual add** by MAC + secret key (for devices not currently advertising, or
  to reuse a key from etrv2mqtt / libetrv).
- **Weekly schedule** support — comfort/setback temperature numbers, a
  human-readable *Weekly schedule* sensor, and the `set_schedule` service. The
  44-byte schedule format was reverse-engineered and verified on real hardware
  (prior projects left it unimplemented).

## v1.0.0
- First stable release: Bluetooth discovery + guided pairing wizard, climate
  entity (manual/schedule/vacation), all device settings (min/max, frost
  protection, adaptive/slow regulation, display flip, mounting, montage, child
  lock), automatic clock sync, vacation service, diagnostics (battery, room
  temperature, RSSI + source proxy, last poll, decoded error flags). Translations:
  English, Polish, German, Danish. Own brand icon/logo. Validated end-to-end on
  Danfoss Eco 2 (014G1001) hardware over an ESPHome Bluetooth proxy.
