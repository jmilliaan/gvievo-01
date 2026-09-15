# gvievo-01 - AGV line-following controller

Onboard Python controller for the EVOTY differential-drive AGV. Two Oriental
Motor BLV-R drives and a SICK MLS magnetic-line sensor share a 125 kbps CANopen
bus. A physical panel starts automatic travel; a Flask HMI provides held manual
jogging and operating diagnostics. RFID tags identify stations and speed zones.

The existing controller has operated on real hardware. The direction-aware route,
high-speed changes and route guards described here have only been tested offline.
This README describes the source, `profiles/agv-01.json` (the vehicle) and
`missions/gy-demo.json` (the site); historical
run logs retain the parameters and behavior of their own software revision.

**Route guards are currently disabled.** Their measurement fields are `null`.
The [hardware commissioning handoff](manuals/today_priority/route-hardware-acceptance.md)
contains the route map, required measurements, 63 hardware test cases (49 that
need motion and 14 for a no-motion session), expected results and recovery
procedures. Run them in the order set by the
[hardware test run sheet](manuals/today_priority/hardware-test-runsheet.md).
All hardware cases remain **NOT RUN**.

## Current profile

| Setting | Value |
|---|---|
| Normal auto cruise | 1000 motor r/min, approximately 0.314 m/s |
| High-speed cruise | 2000 motor r/min, approximately 0.628 m/s |
| Normal/high transition | About 333 r/min/s (3 s nominal), with existing jerk limiting |
| Slow-zone cruise | 800 motor r/min; requires a configured branch slow zone |
| Manual straight / inner curve wheel / spin | 2000 / 1200 / 300 motor r/min |
| Normal gains | `k_ratio=11.3`, `kd=0.94`, `ki=0` |
| Slow-zone gains | `slow_k_ratio=25`, `slow_kd=5`, blended over `gain_blend_s=0.4` |
| CAN nodes | 1 left, 2 right, 10 MLS; sensor TPDO1 is `0x18A` |
| Nominal control / telemetry / field poll | 50 Hz / 5 Hz / 2 Hz |
| Drive acceleration / deceleration | Manual 1000 / 2000; auto 2400 / 3200 r/min/s |
| Manual / auto watchdog | 0.6 s / 1.5 s |
| Automatic start delay | 0.6 s |
| Station stop distance | 0.4 m beyond the detected tag; requires loaded verification |
| RFID repeat-clearance interval | 0.5 s, provisional |
| Route guards | Disabled; distance and station-deceleration limits unmeasured |
| Standing branch preference | Left; `branch_latch` is currently empty |
| Mission | `missions/gy-demo.json`; `missions/empty.json` gives plain line-following |
| `dry_run` | **false** |

Speeds are derived from 180 mm wheels and a 30:1 gearbox. Steering and speed
reduction can lower actual forward speed; motor limits and configured cruise
speeds are different quantities.

## Operating behavior

**This application can move the vehicle and has no authentication.** Port 5000
belongs on the vehicle's trusted operating network.

| Operator action or condition | Behavior |
|---|---|
| Selector in MANUAL | Automatically arms when permitted; retries unsuccessful arming with backoff |
| Hold a manual arrow or arrow-key combination | Sends `/api/drive` every 100 ms; release sends `/api/stop` |
| Manual commands stop arriving | Zeros the command after 0.6 s; holding again can resume jogging |
| AUTO, then physical Start | Arms, waits 0.6 s, starts or continues the route |
| Reset during a run or pending Start | Stops/cancels the run |
| Reset otherwise | Acknowledges a latched controller fault |
| Selector changes | Stops and disarms; MANUAL can then automatically re-arm |
| Station arrival | Distance-based deceleration, followed by a dwell waiting for physical Start |
| Start at a station | Resumes the same run after the start delay |
| Start in MANUAL with a blind-run plan set on `/blind` | Runs the encoder-only move after the start delay |
| Start in MANUAL with a U-turn set on `/blind` | Ignored without tape under the MLS; otherwise pivots 90° or 180° after the start delay |
| Reset during a blind run | Stops it and keeps the plan for a repeat |
| Tape disappears | Coasts within the configured travel grace, then holds the run |
| Tape returns during a hold | Resumes after 2 s of continuously usable tape |
| Drives leave Operation enabled during auto | Holds commands at zero and attempts to re-enable; recovery can resume automatically. Not in a dry run, whose drives are never enabled |
| Route position fault | Stops the run; Start remains refused until recovery at point 2 and process restart |

The web API has no `/api/arm` or `/api/auto/run`. `/auto` is a display page.
Manual jogging requires the vehicle already to be armed in MANUAL. Web disarm
is not a persistent inhibit: a selector left in MANUAL maintains arming.
`/api/stop` is the manual setpoint stop, not an automatic-run latch reset.

Panel-started runs refresh their watchdog from valid panel scans, so closing the
browser does not stop them. The legacy opt-in `/api/state?hb=1` heartbeat remains
available and also refreshes the auto deadline. The auto page claims it;
monitoring pages do not. Observe using `/api/state` without `hb=1` when testing
panel-link loss, so the observer does not refresh the deadline itself.

Normal arming checks drive responses, readable diagnostics, clear error
registers, the Remote bit and absence of FAULT. Failed preflight refuses arming.
AUTO also requires a responding MLS. Guarded departures additionally require
fresh actual-speed feedback from both wheels and a connected RFID reader.

`dry_run` concerns the auto path; it is not an offline simulator or a global
manual-motion inhibit. Auto dry-run leaves the drives unarmed and computes
commands while sending zero targets. Because the drives are never enabled, a
dry run skips the safety-chain hold and its automatic re-enable (see
`_eto_scan`), so no torque is applied. It does not release a motor brake or make
the shafts free to push. MANUAL is unaffected: it still energises the drives,
and a blind run or web jog still moves the wheels with `dry_run` true. Check
error sign by moving a magnet under a stationary sensor. Use the offline tests when no hardware is available.

## Profile and mission files

Configuration is split in two, both loaded once at start-up:

| File | Holds | Changes when |
|---|---|---|
| `profiles/<agv>.json` | The vehicle: geometry, drives, sensors, gains, ramps, network, panel, U-turn dynamics, blind-run limits | The vehicle is rebuilt or retuned |
| `missions/<name>.json` | The site: `branch_latch`, `stop_until_start_button`, `high_speed_mode`, `route`, `route_guard`, `u_turn`, `branch_default`, and `speed` (`auto_rpm_high`, `speed_switch_accel_decel_s`) | The layout, tags or site speeds change |

- **Selecting a mission:** the profile's top-level `"mission"` names it, and
  `$AGV_MISSION` overrides that name. `mission_name` inside the file must match
  its file name, the same rule as `profile_name`.
- **No mission:** `"mission": null`, or `missions/empty.json`, gives plain auto
  line-following and manual jogging. The empty file keeps every key present as a
  placeholder, to copy for a new site.
- **Stale copies are refused:** a site key left in a profile fails as unknown.
  Tags are checked against the profile's RFID reader settings.
- **Route-less missions:** without a route there is no travel direction, so each
  tag must mean one thing. A station tag has one stop distance, a speed tag is
  entry-only or exit-only, and `route_guard` stays off. U-turns, speed zones,
  branch latches and station stops still act, and nothing tracks position.
- **Where to see it:** `/params` and `/api/config` show which mission and file
  are loaded, and each auto run log header records it.

## Route and station identity

The installation uses a shared line, around 90 m total, that ends in a
differential U-turn at each end (tags `0030` / `0031`, replacing the earlier
balloon loops). Four physical stopping positions deliberately reuse two RFID
values. The route is cyclic, and the first `route` row in the mission file is the
assumed startup position.

| Departing station | Departure direction | Next station | Expected arrival tag | High-speed zones allowed on this leg |
|---|---|---|---|---|
| 2 (initial) | Outbound | 3 | `0010` | Yes |
| 3 | Inbound, through upper U-turn | 4 | `0011` | No |
| 4 | Inbound | 1 | `0011` | Yes |
| 1 | Outbound, through lower U-turn | 2 | `0010` | No |

Every station waits for physical Start. Returning to point 2 increments the lap
count; the next Start repeats the cycle. Direction is logical route direction,
not reverse motor motion. Both U-turns are driven forward.

A route row contains `id`, `tag`, `direction`, and `high_speed_to_next`.
`direction` is the **arrival** direction. On departure, the controller adopts the
next station's arrival direction. The direction changes only after the Start
delay completes; cancelling a pending Start does not advance the route.

`stop_until_start_button` supplies `tag`, `direction`, and `stop_distance_m`.
The current distance is 0.4 m for both qualified stop rules. The expected route
stage identifies which station a matching tag represents; direction is derived
from that stage, not independently sensed. For example, outbound
travel passes point 4's `0011` before stopping at point 3's `0010`.

The stop profile is computed from software ramp speed. It is not odometric
position control: driver response, steering, and speed reduction affect the
actual resting position. Station arrival retains the active run and CSV across
the dwell. Distance rather than ramp duration defines the intended resting
point; a fixed duration would change that point with approach speed. Place
station tags on track already straight for about a metre, since steering
remains active during deceleration, and verify stopping with the trailer load.

### State across interruptions

| Interruption | Route state | High-speed latch |
|---|---|---|
| Station dwell | Retained at the confirmed station | Cleared |
| Reset, disarm, end of run | Retained in memory | Cleared |
| MANUAL, then AUTO | Retained in memory | Cleared |
| Line-loss or drive-enable hold | Retained | Cleared; resumes at normal speed |
| RFID loss, guards off | Retains last confirmed stage; stale encounters discarded; warns on mid-run reconnect | Cleared |
| RFID continuity loss, guards on | Faults the run; position confidence invalidated | Cleared |
| Route distance/feedback fault, buffer overrun or missing stop rule | Last logical stage retained for diagnosis; restart of travel refused | Cleared |
| Controller process restart | Assumes point 2, outbound, waiting for Start | Cleared |

Route state does not track manual relocation. If the vehicle is moved past
stations in MANUAL, the preserved logical position can differ from its physical
position. Restart initialization assumes the vehicle is back at point 2.

`route.guard_error` survives Reset, disarm and manual mode. Reset can acknowledge
the controller fault but cannot restore position confidence. For a route fault,
return the vehicle to point 2 and restart the controller. An encounter-buffer
overrun or missing stop rule uses this recovery even when distance guarding is
disabled. Ordinary stops without a route fault retain the existing resume policy.

### Repeated RFID reads

`tags_seen` remains a raw receive counter. A separate ordered encounter buffer
feeds route and branch decisions:

- Repeated reads of a tag are one encounter until it clears.
- A different tag starts another encounter immediately.
- The same value after `rfid.tag_clear_s` without reads starts a new encounter.
- `tag_clear_s=0.5` is provisional and independent of the HMI's 2 s `tag_hold_s`.
- The departed station's reads are suppressed without suppressing other stations.
- Reconnect discards cached encounters and re-baselines the first fresh tag.
  With guards off, a mid-run reconnect warns that a station may have been
  missed; the warning does not recover that arrival. With guards on, loss of
  continuity faults the run instead.
- An encounter-buffer overrun during a run stops it rather than guessing which
  route events were lost.

The former `ignore_t` global station-ignore window has been removed. The loader
rejects that obsolete key. Verify clearance timing against actual reader gaps
and station spacing before running the new route on hardware.

## High-speed zones and control

The same speed-tag pair is reused on both straight high-speed segments:

| Direction | Set high speed | Reset to normal |
|---|---|---|
| Outbound | `0020` | `0021` |
| Inbound | `0021` | `0020` |

Rules live in `high_speed_mode`. The route also gates which legs permit high
speed, so a speed tag on a U-turn leg cannot enable it. Station arrival,
direction change, holds, disarm, and RFID link loss clear the latch.

The mission's `speed.speed_switch_accel_decel_s=3.0` derives about a 333 r/min/s
rate from the 1000 r/min difference between normal and high cruise. The existing
jerk limiter remains active, so completion takes slightly longer than three
seconds (about 3.04 s offline). An exit
received during acceleration retargets the same ramp without jumping its state.
Startup uses the existing acceleration ramp; station stopping uses its own
computed deceleration. Hard stops bypass the cruise transition. Slow-zone mode
has priority over high speed and selects its own steering gains.

The follower scales proportional gain with base speed, filters the derivative,
reduces forward speed with tracking error, and limits wheel commands together.
It prevents derivative kicks after discontinuous track samples. The inner wheel
cannot reverse in auto with the current zero-rpm floor.

| Follower guard | Current value |
|---|---|
| Maximum accepted lateral position | 100 mm |
| Maximum accepted position step | 40 mm |
| MLS freshness timeout | 0.1 s |
| Tape-gap travel grace | 0.075 m, with a derived standstill time limit |
| Integration deadband | 20 mm; integral gain currently zero |
| Control dt bounds | 0.004 to 0.1 s |

RFID encounters are consumed even when a control iteration has no new MLS frame.
The previous wheel command may be retained only while that frame is still
fresh; sensor timeout must still reach the hold path.

A missed high-speed entrance leaves normal speed selected. With route guards
off, a missed exit can leave high speed selected until another reset condition.
With guards on, the measured zone-distance limit provides an additional reset.
Both still require exit placement and deceleration margin before bends/stations;
clearing a latch does not instantly reduce wheel speed.

## Route guards and commissioning limits

`route_guard.enabled` is **false** in the supplied profile. All measurement
fields below are `null`. Enabling requires complete, valid measurements; the
loader rejects incomplete limits and inconsistent station deceleration.

| Setting | Meaning when enabled |
|---|---|
| `legs[].from_station` | Departure station ID; exactly one row for each route station |
| `legs[].min_m` | Minimum plausible estimated travel from departure to the next station tag; earlier matching reads are rejected with a warning |
| `legs[].max_m` | Maximum travel without the expected station; exceeding it faults the run |
| `high_speed_max_m.outbound` / `.inbound` | Estimated travel after a high-entry tag without an exit; expiry selects normal speed and inhibits high until the correct exit |
| `station_decel_limit_rpm_s` | Measured acceptable station-deceleration rate; profile loading checks every stop distance against high cruise and this limit |

Distance is estimated from the latest actual-speed feedback (`606Ch`) from
both wheels, sampled at about 5 Hz. The CAN thread integrates the magnitude of
body-forward speed during active route travel, including temporary holds,
until the station encounter. A genuine departure from a parked station resets
leg distance; restarting an interrupted leg preserves it. Station dwell does
not accumulate distance. Missing/stale speed feedback from either wheel or an
integration gap longer than `driver_timeout_s` (currently 0.6 s) faults a guarded
transit, even if other drive diagnostics remain available.

This estimate is not encoder-position odometry or independent localization.
Slip, sampling delay and wheel geometry affect it. Motion after ending a run
and during manual relocation is outside its integration window. Calibrate
arrival windows against independently marked distances and loaded runs, with
margin for those errors. Choose a maximum that detects a missed station before
the next same-valued tag could be accepted, with room for the fault stop.

The high-speed distance limit is shared by both blue segments within each
direction. It must leave enough room for the measured high-to-normal transition
on the shorter available approach; the longer segment may return to normal
early. Repeated entry reads do not restart the zone-distance budget. Expiry
survives a hold or mid-leg Reset/Start; the correct exit rearms the next segment.

At the current 0.4 m stop distance, normal/high cruise imply calculated rates
of approximately 393/1571 rpm/s. The guard's load-time check conservatively
uses high cruise at every station, covering arrival after a missed exit. If
that exceeds the measured limit, reduce high cruise or commission a longer
stop distance and revised tag placement. Increasing stop distance changes the
resting position and requires remeasuring arrival windows. The rate check is
not a guarantee of physical stopping distance under jerk limiting and load.

Until these guards are enabled and commissioned, a missed station can still
silently shift the logical route stage, and a missed exit can permit a
high-speed station approach. Follow the
[hardware test and measurement procedure](manuals/today_priority/route-hardware-acceptance.md)
before accepting the new behavior on the vehicle.

## Branch selection

`core/branch.py` retains the existing steering ladder independently of route
inbound/outbound state. Configured RFID entry tags latch left/right intent;
returning to one track after a fork consumes that order, with exit tags as a
backstop. A slow-zone latch, if configured, lasts until its exit tag.

Consumed branch/slow-zone encounters still reach the ladder during station,
line-loss and drive-enable holds. Those holds suppress route progression,
not steering inputs. Disconnected or invalidated RFID batches are discarded.

Straight selection follows the track nearest the previously followed position,
using LCP2 initially. Left/right selects the corresponding extreme track;
`#LCP=7` crossings override branch intent with straight selection. The current
empty branch table uses the standing left preference, including at merges.

## Runtime architecture

| Location | Responsibility |
|---|---|
| `main.py` | Stable entry point and import-path setup |
| `config.py` | Strict profile loading, derived constants, validation, HMI parameter descriptions |
| `canworker.py` | CAN thread, vehicle state, panel policy, route integration, watchdogs and recovery |
| `core/route.py` | Pure route progression, high-speed latch and distance-guard state |
| `core/autopilot.py`, `core/kinematics.py` | Steering, speed ramp, body/wheel conversion |
| `core/branch.py`, `core/panel.py` | Branch ladder and debounced panel input edges |
| `drivers/rfid.py` | Chafon TCP thread and tag encounters |
| `drivers/dio.py` | Modbus input/output thread, horn commands and readback |
| `drivers/lidar.py`, `core/lidarframe.py` | nanoScan3 UDP receive, reassembly and decoding |
| `drivers/canbus/` | Shared CANopen primitives and standalone commissioning utilities |
| `core/health.py`, `core/canmon.py` | Device liveness and round-robin drive diagnostics |
| `core/events.py`, `core/runlog.py`, `core/plotrun.py` | Event buffer, CSV, background PNG rendering |
| `core/wifi.py` | Cached Linux Wi-Fi signal readout on the web thread |
| `app/` | Flask routes, local HTML/CSS/JavaScript assets |
| `tests/`, `manuals/`, `logs/` | Offline checks, hardware documentation, recorded runs |

The runtime uses dedicated threads and HTTP polling, not asyncio or WebSockets.
The CAN thread alone owns bus transactions and route decisions. Flask mutates
manual setpoints under a lock or queues slow actions and waits on a Future.
RFID, DIO, and lidar each own their device connection on another thread.

`TpdoTap` routes unsolicited MLS, heartbeat, and EMCY frames while synchronous
SDO calls run. The control loop budgets the remainder of its nominal 20 ms
period; arming and drive recovery include longer blocking transactions while
motion is held. Telemetry runs every 0.2 s; diagnostic SDOs read one object per
node every 0.1 s, completing eleven objects in roughly 1.1 s.

Never perform bus I/O while holding `Controller._lock`: SDO receive can re-enter
sensor callbacks. The RLock is a backstop, and offline structural checks enforce
that bus operations stay outside locked sections.

Layer directories share a flat `sys.path`; they are not packages. Module
basenames must be unique and must not shadow the standard library.
`drivers/canbus/` is a runtime dependency as well as a bench-tool directory.

Control-path events must occur once per transition, not once per scan. The
event buffer holds 200 entries; repeated per-tick messages would erase useful
history. RFID encounters are consumed in order from a frozen batch, once per
scan, independently of whether a fresh MLS frame arrived.

## Hardware health and stopping boundary

The repository documents the physical stopping chain in
[manuals/safety-chain.md](manuals/safety-chain.md): scanner OSSD and operator
inputs feed the FX3, which controls drive torque removal. Lidar UDP data is a
separate diagnostic stream; its zone mapping is currently marked unvalidated.

Software drive-enable recovery deliberately can resume an active run without
another Start press. CAN status is how the controller observes that transition;
it is not a direct measurement of the reason the hardware chain opened.

Device health reporting and control responses are separate:

- Drive heartbeat/SDO evidence feeds the critical 0.6 s watchdog. Loss stops the
  run and latches a controller fault.
- MLS freshness and tape loss are handled by the follower and its hold policy.
- DIO provides panel scans; valid scans feed panel-started auto liveness.
- RFID health uses connection/carrier state, not silence between station reads.
  Loss clears high speed and prevents accepting cached encounters. With route
  guards enabled, RFID continuity loss additionally faults the active run.
- Lidar data loss is diagnostic; it does not replace the hardware stopping chain.

The horn follows nonzero commanded motion on DO0. Its command is renewed by the
CAN thread and written/read back by the DIO thread. Expiry requests low while the
DIO thread and link are functioning; it is not an independent hardware watchdog.
Shutdown attempts to clear claimed outputs before closing the Modbus connection.

The controller's guarded CAN writes permit controlword, operating mode, ramps,
target velocity and heartbeat time. Manufacturer parameter writes, FREE, clear
ETO, parameter store/restore and controlword fault reset are refused. Normal
CiA 402 re-enable remains possible; the write guard is not a no-resume guarantee.

PDO configuration is admitted by rule, because a PDO is a write path by another
name. Nothing in the controller configures a PDO yet; these rules exist so
pushed feedback or a PDO setpoint can be added safely:

- **RPDO mapping:** may name only an object that is itself SDO-writable, and
  never a PDO configuration object.
- **TPDO mapping:** may name anything, since the device only transmits.
- **COB-ID:** must be disabled, or an 11-bit identifier in its own PDO kind's
  predefined range on its own node. An RPDO therefore cannot obey sensor, NMT,
  SDO or another node's traffic, and a TPDO cannot transmit on a command
  identifier.

The guard cannot see PDO frames: anything that sends a controlword by RPDO must
check each value itself (fault reset, bit 7).
See [drivers/canbus/guard.py](drivers/canbus/guard.py) and
[manuals/can-monitoring-plan.txt](manuals/can-monitoring-plan.txt).

## Running and configuration

```bash
python3 main.py                     # 0.0.0.0:5000; landing page /auto
python3 main.py --host 127.0.0.1
python3 main.py --port 5001
AGV_PROFILE=agv-01 python3 main.py
```

Only `agv-01` is currently supplied. `AGV_PROFILE` selects an existing JSON file
in `profiles/`; a missing profile is fatal. The loader rejects unknown/missing
keys, invalid direction/tag combinations, duplicate station IDs, conflicting
rule contacts and inconsistent speeds. See `config.py` tuning notes and the
read-only `/params` page. Profile edits take effect after a process restart,
which also resets route position to its first station.

`/api/config` exposes the route, speed rules, transition rate, clearance interval
and guard configuration. `/api/state` includes guard status, retained route
error and estimated leg/zone distance. `/auto` displays guard on/off or
`POSITION CHECK`; `/params` lists the measurement-dependent guard settings.

Dependencies are `flask`, `python-can`, `pymodbus` for enabled DIO, and
`matplotlib` for run plots; the slcan fallback also uses `pyserial`. Use the
versions validated on the vehicle: this repository does not pin dependencies.
Matplotlib imports lazily when a completed run is rendered, then remains in the
process. Plot failure is captured in `RunLog.error`; the CSV is independent.

The documented production service is `agv_controller.service`, with an entry
point such as `/home/gvipc-evo-01/agv_can/main.py` and
`Environment=AGV_PROFILE=agv-01`. The service unit is not shipped in this repo.
Its shutdown configuration must reach the application's cleanup path; the
existing deployment uses SIGINT and `Restart=on-failure`.

`/api/restart` refuses while armed and checks the systemd restart policy before
shutting down and exiting nonzero. Do not enable `--debug` autoreload on the
vehicle: it can start another controller process.

The HMI polls `/api/state` every 200 ms. `/manual` is the jog pad; `/auto` shows
route and PID state; `/monitor`, `/io`, `/lidar`, `/alarms`, and `/params` expose
diagnostics and settings. All browser assets are local.

### Auto page operating summary

**Point, travel direction, RFID read and route sequence** lead the Auto page.
It shows `TO POINT 3` while travelling, `STOPPING` during deceleration, and
`WAITING FOR START` only once both drives report a fresh speed-zero bit,
alongside OUTBOUND/INBOUND and the sequence 2 -> 3 -> 4 -> 1 -> 2 with its
return boundary and lap count. PID, MLS and RFID diagnostics sit below.

The page never derives route position in the browser. `route_display` carries
the sequence, the next departure direction, a drive-feedback `stopped` verdict
(`null` when feedback is stale) and the **last processed encounter** — sequence,
tag, action, station and reason — so a raw read is never presented as an
arrival. Points 2/3 share tag `0010` and points 1/4 share `0011`, so the raw
value alone cannot identify a station. A failed poll or a gap over 1 s marks the
summary `LIVE STATE UNAVAILABLE` rather than animating stale values.

The [Auto page display plan](manuals/today_priority/auto-page-display-plan.md)
specifies layout priority, state wording, data ownership and acceptance tests.
Offline coverage lives in `tests/test_auto_display.py`; real-DOM coverage runs
via `python3 -B tests/browser_auto.py` (headless Edge/Chromium, fixture-only
HTTP, no device services). Operator verification from the normal viewing
position is hardware case A11 and is **not run**.

### Differential U-turn

A `u_turn` tag (`0030` cw, `0031` ccw) replaces a balloon loop. In AUTO only,
reading one stops the vehicle over `u_turn_stop_distance_m` (0.4 m), then pivots
on its axis with the wheels equal and opposite at `auto_u_turn_rpm`. The MLS
loses the tape as the sensor swings off it, then sees it again near 180°. Past
`u_turn_min_deg`, and at a track level within `u_turn_level_tolerance` of the
start, that ends the pivot: the vehicle centres at no more than half speed until
the error is inside ±`u_turn_center_tol_mm`, holds there for
`u_turn_resume_delay_s` (1 s), and resumes line following.

Encoder travel gates it rather than ending it. `6064h` position is read from
both drives each tick and scaled by `608Fh` (control resolution per motor
revolution) times `vehicle.gear_ratio`; `6091h` must be 1:1 or equal that ratio.
A 180° pivot rolls each wheel π·track/2 = 0.765 m at track 0.487 m, which is
1.353 wheel turns, 40.6 motor turns, or about 1,461,000 counts at the default
36,000 P/R. No reacquisition by
`u_turn_max_deg`, a counter that runs backwards or stalls, a silent sensor, or
any hold during the manoeuvre ends the run with a fault: a half-finished pivot
is not resumed. Reset cancels it quietly.

U-turn tags are not route events. They do not advance the route or change the
high-speed latch, and route tags are ignored while a U-turn is in progress. After
turning, the vehicle drives back over its own tag once; that read is ignored
within the next `u_turn_stop_distance_m` + 1 m of travel. Offline coverage is in
`tests/test_uturn.py`, including a closed-loop pivot model; none of it is
hardware evidence.

### Blind run (encoder-only test moves) and the MLS IMU box

`/blind` exists to measure the drive encoders before SLAM depends on them.
The page **only sets a plan**: one or more segments (straight distance, arc by
radius and angle, pivot by angle, or raw per-drive `6064h` pulses) plus a speed
in m/s or motor r/min. **PB Start runs it**, only with the selector in MANUAL
and the vehicle armed; PB Reset, a selector move, web Stop, a fault, drives
leaving Operation enabled, or `6064h` unreadable for `driver_timeout_s` stops
it. There is no start control on the page and no `/api/blind/start`.

The drives stay in profile-velocity mode. The write guard refuses the
profile-position objects, so a software loop drives the faster wheel on a
trapezoid over its remaining counts. The other wheel follows the planned ratio
plus a progress trim. Each segment ends at rest before its counts are recorded.
Counts per wheel turn come from `608Fh` × `vehicle.gear_ratio`. Whether `6064h`
counts motor-shaft steps (1,080,000 per wheel turn at 36,000 P/R) is not settled
by the manual, and is hardware case E01. The MLS error is logged when tape is
present and never steers.

Each run writes `logs/NNNN-blind_*/run.csv`, and every segment is appended to
`logs/blind_results.csv`. Each row records target and final counts, encoder
distance and heading, and the commanded values. Blank `measured_distance_m` and
`measured_heading_deg` columns are left for tape-measured values. Limits and
tuning are in the profile's `blind_run` section.

The page can also set a **U-turn** instead of a move: 90° or 180°, CW or CCW, at
`autopilot.auto_u_turn_rpm`. It stands in for a U-turn tag read, and unlike a
move it needs the tape: PB Start is ignored without a track under the MLS, and
the turn starts only from rest. 180° is the AUTO pivot (`core/uturn.py`): it
ends when the MLS finds the tape again inside `u_turn_min_deg`..`u_turn_max_deg`,
then centres. On a straight tape nothing is under the sensor at 90°, so 90° ends
on the encoder angle through the blind-run pivot, then centres only if a track
(a crossing tape) is there. The same stop paths apply, and a failed turn stops
without latching a fault. The turn is logged to `logs/NNNN-blind_*/run.csv`, with
the turned angle in `heading_deg`, and adds no `blind_results.csv` row.

The IMU box displays MLS roll/pitch/yaw (`2030h`), acceleration (`2033h`),
angular rate (`2034h`) and temperature (`2070h:01`), read by SDO about once a
second while the MLS streams. These exist only on MLS firmware V5+ with
`2006h:02` = 1; otherwise the box says why. Nothing uses the values yet, and the
MLS is never written.

## Logs and verification

An auto run creates `logs/NNNN-auto_YYYYmmdd_HHMMSS/run.csv` and, on close,
`run.png`. Numbering uses the highest directory prefix currently present plus
one. Station dwells remain within the same run. Ordinary stops keep a 2 s
logging tail; disarm closes immediately.

CSV rows include PID terms, command/feedback speed, statuswords, track selection,
route direction, current/next station, dwell state, lap count, speed mode and
speed target. Guard fields are `guard_enabled`, `guard_error`,
`distance_estimate_m`, and `high_distance_estimate_m`. The header records
normal/high/slow cruise, gains and ramp values. Archive the exact profile with
commissioning evidence; the CSV header is not a complete profile backup.
Rows are buffered and flushed about once per second on the control thread;
PNG rendering runs separately. Actual-speed feedback is sampled at 5 Hz, so its
resolution differs from the approximately 50 Hz command trace.

```bash
python3 tests/run_all.py             # offline; no device services started
python3 -c "import main"             # import/profile check only
```

The runner pins the test modules and check count and fails on uncaught worker
thread exceptions. Latest offline verification on 2026-09-15: **133 test
functions / 1,516 checks passed**, exit 0, without uncaught exceptions, using
Python 3.11.9 on Windows with `PYTHONUTF8=1` (some tests read files with the
platform's default encoding), `profiles/agv-01.json` and
`missions/gy-demo.json`. On 2026-09-14 `tests/browser_auto.py` passed 50
real-DOM Auto page checks at two viewports; it was not rerun. Rerun the suite
with the deployed interpreter/dependencies.

Coverage includes the real
follower against a simulated plant, controller recovery, protocol fixtures,
configuration validation, route laps, repeated equal-valued tags, opposite
travel directions, reconnects, high-speed transitions, and HMI rendering.
Guard tests cover early arrivals, missed stations, zone expiry, stale wheel
feedback, sampling gaps, guarded Start refusal and retained position faults.
Synthetic limits in `tests/test_route_guard.py` are not site measurements.
Offline results do not validate physical stopping distance or RFID coverage.

The [hardware commissioning handoff](manuals/today_priority/route-hardware-acceptance.md)
contains 49 motion cases across normal-speed route, speed/stopping, guarded fault
injection, U-turn, blind-run encoder accuracy and mission checks, plus 14
no-motion cases (Phase N) for hardware sessions where the motors must not turn, with expected
results and an evidence template. Run them in the order set by the
[hardware test run sheet](manuals/today_priority/hardware-test-runsheet.md). All
hardware cases remain NOT RUN. Preserve original run logs as historical
commissioning evidence rather than treating them as tests of this new behavior.
