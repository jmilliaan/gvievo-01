# Direction-aware route and high-speed commissioning handoff

Status: software implemented and tested offline; **all hardware tests below are NOT RUN**.
This document is for the next coding agent and the operator. No conversation
history is needed. Inspect Git status first. `AGENTS.md` is not tracked in Git;
if the vehicle has one, read it, but this handoff does not depend on it.
Use the checked-out code as the authority; `gy-demo-review.md` reviewed an older
commit and several of its findings have since been addressed. Do not restore
the old README or deploy a different revision merely to match that review.

Offline verification on the development PC, 2026-09-15: 133 test functions /
1,516 checks, exit 0, no uncaught thread exceptions, using Python 3.11.9 on
Windows with `PYTHONUTF8=1`, with `profiles/agv-01.json` and
`missions/gy-demo.json` (the empty mission is covered by `tests/test_mission.py`).
On 2026-09-14 `tests/browser_auto.py` ran 50 real-DOM Auto page checks at two
viewports with fixture-only HTTP, 0 failed; it starts no vehicle services and
was not rerun. This is not a substitute for running the suite with the deployed
interpreter and dependencies.

There are two kinds of hardware session. A **motion session** runs the matrix
in section 5 (phases A, B, C, U, E) in the order of the run sheet. A **no-motion
session** runs Phase N plus the few matrix cases that need no wheel motion: the
motors must not turn, and arming or disarming is allowed.

## 1. What is being commissioned

Python controller for two CANopen wheel drives, SICK MLS line sensor, Chafon
RFID reader, Modbus physical panel, and Flask HMI. Runtime uses dedicated
threads. CAN transactions, route decisions and distance integration belong to
the CAN thread. This is not the separate asyncio/fleet project.

The track is approximately 90 m, a shared magnetic line ending in a
differential U-turn at either end (tags 0030 cw / 0031 ccw, replacing the
earlier balloon loops; see Phase U). Outbound goes from the lower end towards the upper end; inbound
returns. The four stop positions reuse two RFID values:

| Physical point | Tag | Arrival direction | Next point after Start | Departure direction |
|---|---|---|---|---|
| 2, lower outbound stop, startup position | 0010 | outbound | 3 | outbound |
| 3, upper outbound stop | 0010 | outbound | 4, via upper U-turn | inbound |
| 4, upper inbound stop | 0011 | inbound | 1 | inbound |
| 1, lower inbound stop | 0011 | inbound | 2, via lower U-turn | outbound |

Every point waits for physical Start. Direction changes when the 0.6 s Start
delay completes, not on arrival or a cancelled Start. The process starts
parked at point 2 outbound; it does not discover its physical location.
Reset/stops/manual preserve logical route state in memory. Manual relocation
past tags is not tracked as route progress. Restore the vehicle to point 2 and
restart the process whenever position confidence is lost.

There are two blue straight high-speed segments. Both reuse the same contacts:

| Direction | High entry | Normal-speed exit |
|---|---|---|
| outbound | 0020 | 0021 |
| inbound | 0021 | 0020 |

High speed is permitted only on legs 2 -> 3 and 4 -> 1. It is prohibited on
both U-turn legs. Current profile: normal 1000 rpm (~0.314 m/s), high 2000 rpm
(~0.628 m/s), slow zone 800 rpm if configured. `branch_latch` is currently empty.
The route, stops, speed zones, guards and U-turns live in `missions/gy-demo.json`,
not the vehicle profile. Its `speed.speed_switch_accel_decel_s=3` derives about
333 rpm/s. Existing 4000 rpm/s^2
jerk limiting stays active: this is not an exact three-second completion promise.
Slow zones override high; startup, station stopping and hard stops retain
their separate behavior. High clears at a station, hold, disarm or RFID loss.

## 2. Software added after the external review

- Test-count guard corrected; arming fake now returns proper SDO upload/download
  replies. Arming must succeed, rather than merely finish its thread. Uncaught
  worker-thread exceptions now make the suite fail.
- Branch/slow-zone encounters are delivered during route holds and departure
  suppression. Route suppression does not suppress steering inputs.
- Unguarded mid-run RFID reconnects emit a warning once. They can still lose a
  station read. Guarded runs instead stop on loss of RFID continuity.
- Missing stop-rule lookup becomes a controller fault, not an uncaught lookup.
- Repeated MLS frames cannot prevent a sensor-timeout stop.
- `/api/config`, `/api/state`, `/params`, the auto page and CSV expose the new
  configuration/state. The route guard is visibly on/off; do not assume it is on.
- The Auto page now leads with point, logical direction, RFID read and route
  sequence; PID/MLS/RFID diagnostics moved below, keeping the junction order and
  reader link/silent/no-cable detail. Wording comes from a structured
  `route_display` record (last processed encounter and its outcome), never from
  a browser-side route or parsed event text. Verify visibility as case A11.
- `/blind` sets an encoder-only test plan (straight, arc, pivot, raw pulses);
  PB Start runs it in MANUAL and Reset stops it. It measures the encoders
  before SLAM. It also shows the MLS IMU, display only. See Phase E.
- `/blind` can also set a 90° or 180° U-turn, CW or CCW, instead of a move. PB
  Start runs it in MANUAL, but only with a track under the MLS and the drives
  at rest. 180° ends on the tape like the AUTO U-turn; 90° ends on the encoder
  angle and centres only if a track is there. See E13.
- A dry-run AUTO run no longer treats its own de-energised drives as a
  safety-chain stop. Before this fix it held the run (suppressing tag reads) and
  then wrote Enable Operation to both drives. To be checked on hardware as N03.
- `route_guard` adds early-arrival rejection, missed-station distance fault,
  distance limit on high-speed zones, speed-feedback freshness checks, and a
  load-time check of high-speed station deceleration against a measured limit.

Route fault recovery requires physically returning to point 2 and restarting
the controller. Reset acknowledges the operator fault but does not clear
`route.guard_error`; Start remains refused. This also applies to RFID encounter
buffer overrun and a missing station rule, even when distance guarding is off.
Ordinary Reset/manual transitions without a route fault preserve the stage.

## 3. Measurement-dependent settings: initially disabled

The supplied `missions/gy-demo.json` has `route_guard.enabled=false`. Its distance
and deceleration measurements are `null`, deliberately not fabricated. With
guards off, the original missed-station and missed-exit risks remain. Do not
report B3/B4 as hardware-validated merely because the software tests pass.

| JSON setting | Required measurement / meaning |
|---|---|
| `route_guard.legs[].from_station` | Departure point, exactly one row for each of 2, 3, 4, 1 |
| `route_guard.legs[].min_m` | Lowest plausible estimated travel from the actual resting/departure position to detection of the NEXT stop tag; shorter matching encounters are rejected |
| `route_guard.legs[].max_m` | Upper travel bound for that same leg; exceeding it faults before accepting another arrival |
| `route_guard.high_speed_max_m.outbound` / `.inbound` | Maximum estimated travel after a high-entry tag without its exit; expiry selects normal speed and inhibits high until the correct exit |
| `route_guard.station_decel_limit_rpm_s` | Deceleration rate supported by loaded stopping tests, in motor rpm/s; not an assumed comfort/safety rating |
| `rfid.tag_clear_s` | Maximum read gaps on a continuously present tag, plus verified margin; currently provisional 0.5 s |
| `stop_until_start_button[].stop_distance_m` | Intended resting distance beyond the corresponding tag, currently 0.4 m |

The estimator integrates the magnitude of body-forward speed calculated from
the latest LEFT/RIGHT actual-speed SDOs (`606Ch`), sampled at about 5 Hz. Wheel
inversion is applied through `kinematics.wheels_to_body`. Integration runs on
auto ticks, including temporary holds while the run remains active, until the
station encounter. It is NOT encoder-position odometry or independent
localization. Slip, sampling delay, wheel dimensions, and motion after an
operator stop or during manual relocation can create distance error. The last
two are outside its integration window. Do not move the vehicle manually and
then treat the preserved estimate as a newly measured leg.

Fresh speed feedback from both drives and a connected RFID reader are required
to start a guarded leg. A speed sample or integration gap over
`timing.driver_timeout_s` (currently 0.6 s) faults a guarded transit. Station
dwell does not accumulate distance. Actual departure from a parked station
resets leg distance; restarting a stopped run mid-leg preserves it. A position
fault is retained until process restart.

Calibrate arrival windows against the logged estimate AND independently marked
physical distances, unloaded and loaded, in both directions. Choose enough
tolerance for measured error without allowing the later same-valued station
to fit the earlier station's window. The maximum must leave room for the
fault-stop distance before a hazard, not merely detect a mistake after it.

The speed-zone budget is shared by both segments within a direction. Choose it
to force normal speed sufficiently early for the SHORTER available approach
to a bend/station, allowing the measured high-to-normal transition and estimator
error. A longer segment may therefore return to normal early. Do not simply
use the longest blue segment plus margin. If no useful common bound exists,
keep high speed disabled on the route legs until segment-specific identification
is implemented; do not weaken the bound to pass a test.

Normal/high stop-rate calculations at the current 0.4 m are approximately
393 / 1571 rpm/s. The configured limit is checked against **high speed at every
stop**, conservatively covering a missed exit. If validation refuses it, reduce
high cruise or commission longer stop distances and tag placement. Increasing
stop_distance_m moves the intended resting point and requires remeasuring the
arrival windows. The mathematical rate check does not guarantee a physical
stopping distance: jerk, drive response, load and traction still need testing.

Continuous reads already suppress repeats; `tag_clear_s` does not inherently
need to exceed the full field-transit time. Measure internal read gaps and
actual clearance, including marginal tag alignment. A different tag creates
an encounter immediately. The reader only knows received values and timing;
it cannot physically prove two identical values came from different tags.

## 4. Agent preparation and evidence

1. Record `git rev-parse HEAD`, branch, `git status --short`, and a patch of local
   changes. Preserve the exact profile and mission file used for each test; do not overwrite
   historical run folders. Record vehicle, load/trailers, floor conditions,
   operator, date and software revision.
2. Run `python3 -B tests/run_all.py` from the repository root on the target's
   existing Python environment. On the development Windows PC the verified
   interpreter is `D:\anaconda3\python.exe -X utf8 -B tests/run_all.py`.
   Require exit 0, the check count pinned in `tests/run_all.py`, no failed
   checks and no uncaught exceptions. Do not install/upgrade vehicle packages
   just to match a developer environment. Dependencies include Flask,
   python-can, pymodbus and matplotlib.
3. Verify the deployed working directory, profile and mission (including any
   `AGV_PROFILE` / `AGV_MISSION` environment) against the live service
   configuration (`systemctl cat agv_controller.service` where applicable).
   Do not launch `main.py` alongside the running service: two processes must
   not own the CAN bus. `dry_run` is not an offline simulator or a global
   manual-motion inhibit. For a stationary sensor-only test, auto dry-run
   leaves the drives de-energised and sends zero targets; it does not make a
   braked shaft free to push. MANUAL still energises the drives, and a blind
   run, a `/blind` U-turn or a web jog still turns the wheels with `dry_run` true.
4. Record `/api/config`, `/api/state`, and `/api/events?since=0` via read-only
   HTTP on the vehicle. Poll `/api/state` without `hb=1` for an observation-only
   client. The actual auto page claims a legacy heartbeat, so browser state
   matters when testing the panel-link watchdog. Event ring is only 200 items:
   save it incrementally using returned sequence numbers.
5. Coordinate motion with the physical operator. AUTO Start arms and starts
   after the delay; Reset stops/cancels; MANUAL automatically arms. There is no
   `/api/arm` or `/api/auto/run`. `/api/stop` is a MANUAL setpoint stop, not an
   AUTO run stop. Do not repurpose web endpoints or standalone CAN tools to
   bypass this panel policy or the hardware stopping chain.
6. Start with guarded distances OFF and high-speed permission OFF on both long
   route legs for controlled normal-speed measurement runs. Keep the normal/
   high RPM relationship valid; setting both RPM values equal fails validation.
   Restart after profile or mission changes only while stopped, at the assumed
   initial point 2. High-speed permission, guards and stop distances are edited
   in `missions/gy-demo.json`; each change is a commissioning change to record.

Evidence per motion case: auto CSV and PNG under `logs/NNNN-auto_*`, event
capture, before/after state snapshots, physical distance/time observations and
copies of the profile and mission file. CSV now includes direction, current/next station, lap, speed
mode/target, `guard_enabled`, `guard_error`, `distance_estimate_m`, and
`high_distance_estimate_m`. The last two are estimates, not ground truth.

## 5. Hardware test matrix

All rows start NOT RUN. Run them in the order set by
[hardware-test-runsheet.md](hardware-test-runsheet.md), not the phase order
below: the U-turn replaced the balloon loops, so every full-lap case depends on
Phase U passing first. A coding agent can
collect evidence and evaluate it; tests requiring movement or physical tag/link
changes need the operator. Do not mark them passed from simulated results.

### Phase A: stationary checks and normal-speed route

| ID | Procedure | Pass / required evidence |
|---|---|---|
| A01 | Confirm node IDs (left 1, right 2, MLS 10), RFID/DIO links and live panel DI labels; check Start/Reset/selector one at a time while stationary | HMI input labels match physical controls; no unexpected motion command; correct profile, mission and service (`/params` shows both) |
| A02 | Stationary sensor-only sign check using a magnet under MLS, with the appropriate dry-run setup; never push a braked vehicle for this | Correct lateral sign and steering command sign; fresh MLS frames; auto dry-run target stays zero |
| A03 | In a controlled low-speed test, silence MLS frames while preserving the rest of CAN communication; include repeated last-frame observations | Sensor age over 0.1 s reaches sensor-loss hold and commands stop; previous target is not retained indefinitely. Restore valid tape and verify existing 2 s stable-tape auto-resume behavior |
| A04 | At point 2, press Start then Reset before 0.6 s; repeat at point 3 and point 1 | Pending Start cancels; route/direction do not advance. Completed departures from 3/1 select inbound/outbound respectively |
| A05 | With high-speed legs disabled, perform two complete cycles 2 -> 3 -> 4 -> 1 -> 2, pressing Start at every stop | Correct physical stop order, direction and lap count; pass-through reads of opposite-direction stations do not stop; each station dwells indefinitely for Start |
| A06 | Hold a tag continuously in the reader field; measure raw read-gap distribution, marginal alignment, removal/return and two separated identical-valued tags | One encounter for continuous reads, fresh encounter after actual clearance, next same-valued station accepted. Record maximum internal gaps and field length; tune and repeat tag_clear_s tests |
| A07 | Reset and restart mid-leg without relocating; switch MANUAL/AUTO while stationary; restart the process at point 2 | Logical stage preserved through stops/manual; high cleared. Process restart resets to point 2 outbound. Do not restart mid-track and expect localization |
| A08 | Exercise existing line-loss and hardware drive-enable/ETO holds with operator control | High clears, stage preserved, existing automatic re-enable/resume behavior verified and understood. Hardware stopping chain remains independent of lidar UDP diagnostics |
| A09 | Stationary/unloaded branch fixture with temporary, nonconflicting branch entry/exit tags; exercise line/drive/station holds | Branch/slow entry and exit still update the ladder during holds; route itself does not advance. Restore original empty branch_latch afterward |
| A10 | Collect independently marked leg lengths and logged estimated distances at all four station arrivals, including repeated normal-speed loaded runs | Establish min/max windows and estimator error distribution from actual departure resting point to next tag read; no fabricated thresholds |
| A11 | With the operator standing at the normal viewing position, read point, direction, tag and sequence off `/auto` through a full lap, both U-turn departures, a cancelled Start and a deliberate hold; repeat on the installed HMI and on a phone | Point/direction/tag legible without leaning in; wording matches physical position at every stop; deceleration reads as `STOPPING`, not `WAITING FOR START`; pass-through 0010/0011 reads never claim arrival; stopping the poll shows `LIVE STATE UNAVAILABLE` rather than stale values. See the Auto page display plan |
| A12 | Stopped at point 2, restart the service with `AGV_MISSION=empty` and run a short plain line-follow; then restart with `missions/gy-demo.json` and repeat one A05 lap | Empty mission: `/params` and `/auto` show mission `empty` and NO ROUTE, auto follows tape until Reset, no station stops or speed changes. gy-demo: route restored at point 2 outbound and A05 behaviour unchanged. Record both mission files |

### Phase B: controlled speed and stopping measurements

Provide sufficient clear runout and use a controlled straight before the full
route. Restore only the intended long-leg high-speed permissions. Begin
unloaded, then repeat with the intended trailer/load conditions. Stop the test
if actual stopping/steering behavior exceeds the agreed test area.

| ID | Procedure | Pass / required evidence |
|---|---|---|
| B01 | On each blue segment outbound, read 0020 then 0021; inbound read 0021 then 0020 | Entry selects high, exit normal, correct direction; reused pair works twice per long leg; both U-turn legs remain normal despite these tags |
| B02 | Measure stable normal -> high -> normal; also exit during acceleration | Nominal reference uses about 333 rpm/s with jerk limiting, no reference jump; record actual duration, travel and wheel feedback. Approximately 3.04 s / 1.43 m is only an offline reference for high -> normal |
| B03 | If using slow-zone fixtures, overlap high with slow; test station stop and controlled hard stop separately | Slow wins; station rate is its own calculation; hard stop collapses software reference to zero. Actual wheel deceleration is captured, not inferred from the command |
| B04 | Measure normal and high approach stops on a controlled straight, unloaded and loaded, before allowing high near operational stations | Record tag-to-rest distances, overshoot, trailer behavior and peak/settled deceleration. Set measured station_decel_limit_rpm_s. Do not accept a mathematical 0.4 m as a measured stop |
| B05 | Measure available entry/exit-to-bend/station distances on BOTH blue segments in BOTH directions, with loaded transition data | Exit placement and shared per-direction high-distance limits leave room for transition plus estimator error before normal speed is required |
| B06 | Repeat read-gap/clearance tests at high speed and with actual tag alignment | No duplicate encounter or missed necessary station/exit read in the tested runs; document detection failures rather than discarding them |

### Phase C: guards enabled and fault injection

Fill every `route_guard` measurement in the mission file, validate it with the
profile, then enable it.
Archive both the measured data and the chosen margins. Do not use synthetic
values from `tests/test_route_guard.py`. Use a reduced-speed controlled test
area first for deliberate missed tags, then the approved loaded test conditions.

| ID | Procedure | Pass / required evidence |
|---|---|---|
| C01 | Enable guards with complete measured settings; separately try a copied mission file with a missing bound or overly low station deceleration limit using offline validation | Valid mission loads; invalid missions are refused with the offending setting. Live `/api/config`, `/params` and HMI show guard on |
| C02 | Introduce an extra matching station tag before the calibrated minimum distance in a controlled setup | Early-arrival warning; no false station/lap advance; correct later tag accepted inside window |
| C03 | Deliberately omit the expected station read while ensuring a clear fault-stop area, separately for each leg | Exceeding max_m stops the run and names expected station; later equal-valued tag cannot be accepted as that station; guard_error remains after Reset; Start refused until recovery at point 2 and process restart |
| C04 | Omit a speed exit in each direction/segment, with adequate clear transition distance | At high_speed_max_m, warning once, target transitions to normal; repeated entry cannot restore high; correct exit then a new entry rearms the next segment |
| C05 | Stop/hold mid-zone and resume without relocating; also Reset/Start after a zone has expired | Stage/leg estimate retained, high cleared on hold; expired-zone inhibition survives restarting mid-leg and cannot be bypassed by another entry |
| C06 | Interrupt RFID while travelling in controlled conditions; reconnect with the next station tag in the field; include a rapid reconnect between controller scans | Guarded run stops on continuity loss without inventing arrival; point stays at last confirmed station; no automatic motion restart. With guards OFF the different expected behavior is warning/normal speed, not this fault |
| C07 | Bench/instrumented controlled test: suppress one drive's speed-feedback responses while preserving other liveness traffic | Guarded transit faults when that wheel's speed age exceeds 0.6 s; a healthy statusword alone must not make stale speed valid. Do not disconnect the whole CAN bus and claim this isolates the feedback guard |
| C08 | Bench/instrumented test of a control sampling gap over 0.6 s, including fresh feedback on return | Route distance confidence faults before the next motion command; never clamp away the missing interval and continue. Do not intentionally freeze a live moving controller outside a controlled bench setup |
| C09 | Full normal and high-speed cycles after all fault cases pass, with operational trailer loads | Every stop, lap, speed segment, direction change and recovery correct; margins remain valid; event warnings/faults occur once per transition and logs match physical observations |
| C10 | Panel/drive watchdog tests, using read-only observer requests and explicitly controlling whether the auto browser is open | Record actual stop behavior and trigger source. Legacy hb=1 may refresh the auto deadline; do not claim exclusive panel-link watchdog behavior if the browser masks it |

An encounter-buffer overrun and missing configuration rule are already covered
offline; do not flood real RFID traffic or corrupt a live controller solely to
repeat those cases. Their deployed fault display can be checked on a bench.

### Phase U: differential U-turn (added after this handoff; all NOT RUN)

The U-turn replaces the balloon loops. It is AUTO only and independent of the
route. The encoder scale is an assumption until U01 passes: counts per wheel
turn = `608Fh` resolution x `vehicle.gear_ratio`, with `6091h` 1:1 or equal to
that ratio. Offline tests use a synthetic pivot model only.

| ID | Procedure | Pass / required evidence |
|---|---|---|
| U01 | Stationary, unloaded, wheels raised or on a turntable: arm AUTO, record the logged "U-turn encoder scale" event plus `608Fh`/`6091h`. Rotate one wheel a marked whole number of turns and compare `6064h` change | Counts per wheel turn match the logged scale within 1%. If not, the U-turn must not be run until the scale source is corrected |
| U02 | Controlled area, both tags: drive over `0030` and `0031` at normal speed | Stop over about 0.4 m past the tag; pivot direction matches cw/ccw seen from above; `u_turn_deg` in the CSV ends 170-190 deg; final MLS error within ±10 mm; 1 s dwell, then forward line following |
| U03 | Record MLS track level at the start and on reacquisition for both directions and both ends, with the actual tape and floor | Reacquisition level within `u_turn_level_tolerance`; tape lost before `u_turn_min_deg`. Tune only from recorded levels |
| U04 | Repeat U02 from high speed where a U-turn tag follows a high leg, and with the operational trailer | Stopping distance and pivot stay inside the clear area; trailer tracking acceptable. Stop the test if the trailer binds |
| U05 | Obscure the far tape (or offset it) so reacquisition cannot happen, with a clear fault-stop area | Fault by `u_turn_max_deg`; wheels stop; run ended; Start refused until Reset; fault text names the U-turn |
| U06 | Trigger a line-loss or ETO hold mid-pivot, and Reset mid-pivot | Hold: run ends with a U-turn fault, no automatic resume. Reset: pivot cancelled without a fault |
| U07 | After a completed U-turn, drive back over the same tag, then complete a full route lap | The pass-over read is ignored once; the next genuine read of that tag turns again; route stations and lap count unaffected |
| U08 | Check drive behaviour at the half-speed centring command (75 r/min at the current setting) and below | Smooth motion without stalling or hunting at low speed; if the drive cannot hold it, raise `auto_u_turn_rpm` or `u_turn_center_kp_rpm_per_mm` and repeat U02 |

### Phase E: blind run and encoder accuracy (added after this handoff; all NOT RUN)

`/blind` sets an encoder-only plan and PB Start runs it (selector MANUAL, armed);
Reset stops it. The purpose is to measure encoder accuracy before SLAM. Every
segment is appended to `logs/blind_results.csv`; write the tape-measured values
into its blank `measured_distance_m` / `measured_heading_deg` columns and keep
the file with the evidence. No tape guard applies to a blind run: use a clear,
marked floor with the lidar protective fields and E-stop verified. The encoder
scale is the same assumption as U01: `608Fh` x `vehicle.gear_ratio`.

| ID | Procedure | Pass / required evidence |
|---|---|---|
| E01 | Wheels raised: pulses segment of one wheel turn per drive at the logged scale (1,080,000 counts if motor-shaft); mark both wheels | Each wheel turns one revolution within 1%. Records whether `6064h` is motor-shaft or gear-shaft. Run with U01 |
| E02 | IMU box with the MLS streaming, at rest; tilt the vehicle a few degrees; note temperature | Either plausible values (about 9.8 m/s² on one axis at rest, roll/pitch following the tilt) or a clear "not available" reason. Record MLS firmware and `2006h:02`. Nothing is written to the MLS |
| E03 | Interlocks: Start in MANUAL with no plan; Set while running; Reset mid-run; selector to AUTO mid-run; web Stop mid-run; a fault; ETO mid-run; close the browser mid-run | No plan: ignored. Every stop path stops and names its cause. Closing the browser does not stop a panel-started run. Nothing on the page can start the wheels |
| E04 | Straight 1 / 3 / 5 m forward and reverse, 3 runs each, on tape, unloaded | Measured vs encoder distance per run; effective wheel diameter; MLS lateral drift from the run CSV |
| E05 | Pivot 90 / 180 / 360°, CW and CCW, 3 runs each, with floor marks | Measured vs encoder heading; effective track width |
| E06 | Arcs R = 1 m and 2 m, 90° left and right | End position and heading vs plan |
| E07 | UMBmark: 4 m square (straight 4 m + pivot 90° x4) CW and CCW, 5 runs each | Return-position error clusters for each direction; systematic wheel-diameter-ratio and track errors |
| E08 | 3 m straight at 0.1, 0.3 and 0.6 m/s | Encoder scale independent of speed, or the measured dependence |
| E09 | Final counts vs target over all runs | Stop-error distribution. Kept separate from encoder accuracy: counts at rest are what E04-E08 compare |
| E10 | Repeat E04, E05 and E07 with the operational trailer | Load effect on diameter, track and slip |
| E11 | Off-tape run on a clear floor area | Same behaviour with the MLS showing no tape; nothing steers |
| E12 | Loop timing (`loop_ms` in the blind CSV) and bus load during runs with per-tick `6064h` SDO reads | Decide whether the drives' SYNC-triggered TPDO3 (`6064h`, default mapping) is needed for faster feedback |
| E13 | `/blind` U-turn, selector MANUAL, unloaded, clear circle. First wheels raised: Start with no magnet under the MLS; then with a magnet under it, and removed as soon as the wheels turn, 90° CW/CCW and 180° CW (centring has no time limit, so a magnet left under a body that cannot rotate keeps it centring until Reset). Then on the floor on straight tape: 180° CW/CCW and 90° CW/CCW, Reset mid-turn once | No tape: Start ignored with "needs the tape". Wheels raised: 90° completes by encoder; 180° stops with "not reacquired" by `u_turn_max_deg` and latches no fault. On tape: 180° ends centred within ±10 mm with `heading_deg` 170-190; 90° stops within a few degrees by floor mark and reports not centred. Reset stops the turn and keeps the plan |

### Phase N: no-motion hardware session (motors must not turn; all NOT RUN)

Purpose: exercise, on the connected hardware, everything that does not need a
wheel to turn. **The motors must not turn at any point.** Arming and disarming
are allowed. Phase N evidence never passes a motion case in phases A-E: those
stay NOT RUN in a no-motion session, with the Phase N case that covered part
of them named in the results file.

**What can and cannot turn a motor.** Read this before any case.

| Action | Motor effect | Allowed in a no-motion session |
|---|---|---|
| Selector to MANUAL | Arms: drives energised, velocity held at zero | Yes |
| Selector to AUTO, `/api/disarm`, `/api/stop` | Disarm or zero setpoint | Yes |
| PB Start, selector AUTO, `dry_run` **true** | Sensor-only arm, drives de-energised, targets zero | Yes, after N01 |
| PB Start, selector AUTO, `dry_run` false | Arms and drives the route | **No** |
| PB Start, selector MANUAL, a move or U-turn set on `/blind` | Runs it | **No** |
| PB Start, selector MANUAL, `blind.plan` null | Ignored | Yes, only after checking `/api/state` |
| `/manual` page open in a browser, `/api/drive` | Jog (arrow keys jog too) | **No**, never open `/manual` |
| SET / CLEAR on `/blind` | Stores or discards a plan only | Yes, in N11; CLEAR before leaving |
| Standalone CAN tools, `main.py` next to the service | Uncontrolled bus access | **No** |

**Session rules**

- **Dry run is the gate for every AUTO Start.** `autopilot.dry_run` must read
  `true` on both `/params` and `/api/config` since the last restart.
- **Watch the setpoint all session.** Poll `/api/state` without `hb=1`.
  `target.left` and `target.right` must stay 0, and `nodes["1"].rpm` and
  `nodes["2"].rpm` must stay 0 apart from reading noise. During a dry-run AUTO
  run `nodes[*].state` must never reach Operation enabled.
  - If any of these is violated, the operator presses the E-stop, the session
    stops, and the agent reports it.
- **Second barrier:** raise or chock the drive wheels where possible. This does
  not make motion allowed.
- **Tags:** present hand-held tags at the reader antenna, the way a tag passes
  in service.
- **Track under the MLS:** dry-run AUTO cases need one. Use the service tape if
  the vehicle is parked on it, otherwise a loose strip of the same magnetic tape
  laid under the sensor. Record which.
- **Restarts:** only disarmed (selector AUTO, no run). Use `/api/restart`: it
  de-energises, exits, and relies on the unit's `Restart=on-failure`. It refuses
  while armed.
- **Encoder scale:** `608Fh`/`6091h` are read only by a MANUAL arm and are
  forgotten at restart. Put the selector in MANUAL once after the latest restart
  before N06.
- **Files:** every profile or mission edit is agreed with the operator, copied
  into the evidence folder before and after, and followed by a restart.

| ID | Procedure | Pass / required evidence |
|---|---|---|
| N01 | Dry-run gate. Selector AUTO, disarmed. Set `autopilot.dry_run: true` in `profiles/agv-01.json`, restart, reload `/params` and `/api/config` | Both show `dry_run` true, profile `agv-01` and the intended mission. The before/after profile copies differ only in `dry_run` |
| N02 | MANUAL arm without motion. Selector MANUAL; read `/api/state` for 30 s. `POST /api/restart` once while armed. `POST /api/disarm` once. Selector back to AUTO | Armed in manual; both drives Operation enabled; `target` 0/0; rpm 0. Event `encoder scale N counts per wheel turn` (record N; 1,080,000 means 36,000 P/R x gear 30), or the warning naming why not. `sensor_age_s` stays under 0.1 s. `/api/restart` refused with "the vehicle is armed". `/api/disarm` de-energises, then MANUAL re-arms by itself. Selector AUTO disarms. Supplies the scale part of U01/E01 only |
| N03 | Dry-run AUTO arm and run (checks the dry-run fix on hardware). Selector AUTO, track under the MLS, press Start, observe at least 30 s, press Reset | Event `armed DRY RUN - drivers de-energised, sensor only`. The run starts after 0.6 s with a new `logs/NNNN-auto_*`. Throughout: `nodes[*].state` never Operation enabled, `target` 0/0, `eto_hold` null, no `torque restored` or `RESUMING` event. `pid.v_base` ramps to `auto_rpm` as a software reference only. Reset ends the run and AUTO then disarms. **FAIL** if a drive is enabled or a safety-chain hold appears |
| N04 | Logical route with hand-held tags, gy-demo, guard off, dry run. Steps: (1) after a restart `/auto` shows INITIAL POSITION ASSUMED at point 2; (2) Start; (3) present `0011`; (4) present `0010`; (5) Start then Reset within 0.6 s; (6) Start; (7) present `0010`, then `0011`; (8) Start with `0011` still held; remove it longer than `tag_clear_s`, present it again; (9) Start, then Reset mid-leg, then Start; (10) selector MANUAL then AUTO mid-leg, then Start; (11) present `0010`; (12) restart | (2) TRAVELLING to point 3, outbound. (3) no stop, encounter `no route action`. (4) `station accepted` at point 3, `stop_hold` `0010`; record `route_display.stopped` and the status word shown. (5) start cancelled; still point 3, outbound. (6) departs inbound toward 4. (7) `0010` no stop; `0011` arrives at 4. (8) the held tag causes no stop (no new encounter, or `suppressed` / `departed station repeat`); the re-presented tag arrives at 1. (9) and (10) stage and direction kept. (11) arrives at 2, laps 1. (12) point 2 outbound, laps 0. At every step the `/auto` wording is legible from the viewing position and matches the logical position. Cutting the viewing device's network shows LIVE STATE UNAVAILABLE within about 1 s. Covers the logic of A04, A05, A07 and part of A11 |
| N05 | High-speed zone logic, shipped gy-demo (`high_speed_to_next` true at points 2 and 4), dry run. On leg 2 -> 3 present `0020` then `0021`. On leg 3 -> 4 present `0021` then `0020`. On leg 4 -> 1 present `0021` then `0020`. On leg 2 -> 3 present `0020`, then arrive at 3 with `0010`. Present `0020` on a high leg and unplug the reader | Leg 2 -> 3: `0020` gives `pid.speed_mode` high, `speed_target_rpm` 2000 and event `speed mode high (tag 0020)`; `0021` gives normal. Leg 3 -> 4 stays normal. Leg 4 -> 1: `0021` high, `0020` normal. Arrival and reader loss each clear high. CSV `v_base` changes at about 333 r/min/s: a software reference, not wheel speed. Covers the logic of B01 |
| N06 | U-turn tag in dry run. Selector MANUAL once since the latest restart (scale read), then selector AUTO and a dry-run run. Present `0030`; observe up to 60 s; Reset. Repeat with `0031` | `u_turn.active`, phase `stopping`; station tags presented meanwhile are suppressed; `target` 0/0 throughout. Record which outcome follows. (a) Phase stays `stopping` because the de-energised drives do not report speed-zero; Reset ends it quietly, no fault. (b) Phase `spin` starts; the wheels never turn, so about 30 s later the run faults with `U-turn spin exceeded 30 s at 0 deg by encoder` (a CW turn may print `-0 deg`). **FAIL**: any nonzero target, `U-turn encoder position (6064h) unavailable` (blocks all U-turns and blind runs), `U-turn needs the drive encoder scale` after N02 read one, or a fault text that does not match. Covers tag recognition of U02 only |
| N07 | Line-loss hold, dry run, only with a loose strip under the MLS. During a dry-run leg slide the strip out; after the hold appears, put it back and keep it still for 3 s | `auto_hold` names the line loss within a fraction of a second (the 0.075 m grace is software travel); high speed cleared; route stage kept. About 2 s of stable track resumes the run. NOT RUN if the vehicle is parked on the service tape. Covers the line part of A08 |
| N08 | RFID link loss, guard off, dry run. On a leg with high selected (N05), unplug the reader's network cable for 10 s, reconnect. Present the next station tag, remove it longer than `tag_clear_s`, present it again | `/auto` shows the reader down or NO CABLE; high cleared; no stop and no fault. On reconnect, one warning `RFID link re-established mid-run; a station may have been missed`. The first read after reconnect is only a baseline; the re-presented tag is accepted as the station. Covers the guards-off side of C06 |
| N09 | Panel DI link loss, dry run, every `/auto` page closed (observers without `hb=1` only). During a dry-run leg unplug the DIO module's network cable; after the fault, reconnect and press Reset. Repeat once with `/auto` open on one device | Page closed: the run ends within `auto_watchdog_s` (1.5 s) with fault `watchdog: panel scan stopped - DI link lost`; Reset after reconnect clears it. Page open: record whether the run continues, since the page's legacy `hb=1` can mask the loss. Record only, not a pass criterion. Covers part of C10 |
| N10 | E-stop with MANUAL armed. Selector MANUAL, armed; operator presses the E-stop for 10 s, then releases it | Drives leave Operation enabled; event `drives are no longer enabled - re-arming`; `cannot arm in manual: ... - retrying` once, retries every 2 s; no fault latched. On release the vehicle re-arms, drives Operation enabled, `target` 0/0. Covers the MANUAL side of A08 |
| N11 | `/blind` page without Start. (1) After a restart, selector AUTO, no MANUAL arm yet: SET a straight 0.1 m, then SET 90° CW. (2) Selector MANUAL: SET a straight 0.1 m. **Do not press Start.** (3) SET 180° CCW, then SET 90° CW. (4) SET an arc with radius 0.1 m. (5) CLEAR. (6) Only after `/api/state` shows `blind.plan` null: press PB Start | (1) Both refused `encoder scale unknown`. (2) Plan table shows one row; status PLAN SET - PRESS START ON THE PANEL. (3) Each replaces the plan: note ends `on the tape` for 180°, `on the encoder angle` for 90°. Status reads PRESS START or NO TAPE UNDER THE MLS, matching the tape tile. (4) Error names `radius_m` must be at least half the track; plan unchanged. (5) NO PLAN SET, `blind.plan` null. (6) Event `Start ignored - selector is in MANUAL and no blind-run plan is set on /blind`; nothing starts. `target` 0/0 throughout. Covers the web parts of E03 and E13 |
| N12 | Empty mission, dry run. Confirm the unit sets no `AGV_MISSION`. Set profile `"mission": "empty"`, restart. Dry-run Start; present `0010`, `0011`, `0020`, `0021`, `0030`; Reset. Restore `"mission": "gy-demo"`, restart | Empty: `/params` shows mission `empty` from `missions/empty.json`; `/auto` shows NO ROUTE and LINE FOLLOWING; no station stop, speed mode stays normal, no U-turn. gy-demo restored: point 2 outbound, INITIAL POSITION ASSUMED. NOT RUN if `AGV_MISSION` is set in the unit. Covers the display and logic of A12 |
| N13 | Mission validation on the vehicle, no restart. Copy `missions/gy-demo.json` into a scratch folder outside `missions/` as: a valid copy; `route_guard.enabled` true with null bounds; guard enabled with complete bounds but `station_decel_limit_rpm_s` 100; `u_turn[0].tag` `0010`; `stop_until_start_button[0].direction` `north`; a copy whose `mission_name` differs from its file name. Each file's `mission_name` equals its file name except the last. From the repository root: `python3 -B -c "import config; config.load(mission='<file>'); print('loaded')"` | Valid copy prints `loaded`. The others are refused with, in order: `measurement required before enabling route_guard`; `high-speed station stop exceeds measured deceleration limit`; `tag 0010 is ignored or assigned to another rule type`; `direction must be outbound or inbound`; `rename one to match the other`. `import config` reads files only and opens no hardware. Nothing under `missions/` changes. Covers the validation part of C01 |
| N14 | Route guard with a placeholder mission, **dry run only**. Stopped, disarmed, N01 confirmed. Create `missions/nomotion-guard.json`: gy-demo with `mission_name` `nomotion-guard`, `route_guard.enabled` true, every leg `min_m` 0.5 and `max_m` 1000, both `high_speed_max_m` 1000, `station_decel_limit_rpm_s` 3200. Point the profile's `mission` at it; restart. Steps: (1) check `/params`, `/api/config`, `/auto`; (2) reader unplugged, press Start, then Reset; (3) reader connected, Start; (4) present `0010`; (5) unplug the reader mid-run; (6) reconnect, Reset, Start; (7) restart; (8) restore `mission` gy-demo, restart, move the placeholder file into the evidence folder | (1) Guard shown on. (2) Refused with fault `route guard: RFID connection required`; Reset clears it. Speed feedback is checked first: if the fault is `fresh speed feedback from both drives required` instead, the de-energised drives are not reporting actual speed; record it and skip to (7). (3) Departs toward 3. Any `speed feedback stale or distance sampling interrupted` fault during the leg is a finding to record. (4) Warning `early tag 0010 rejected; expected station 3 farther along leg`, no arrival (expected: dry-run distance stays 0). (5) Fault `route guard: RFID continuity lost; return to point 2 and restart controller`; `/auto` POSITION CHECK REQUIRED. (6) Reset clears the operator fault but `route.guard_error` stays; Start refused again. (7) `guard_error` cleared, point 2. (8) Guard off; `missions/` holds only the original files. The placeholder values say nothing about arrival windows and must never run with `dry_run` false. Covers the RFID-continuity parts of C02 and C06 |

**Matrix cases a no-motion session may run.** Only these, and only as written:

- **A01**, with `dry_run` true, so pressing Start in AUTO cannot drive.
- **A02**, only with a loose strip or magnet under a vehicle parked off the
  service tape.
- **A06**, with hand-held tags.
- **E02.**

For A06, `tag_age_s` in `/api/state` resets on every read, so its peak while a
tag is held continuously is the longest read gap. Poll at 10 Hz or faster.
Every other matrix ID is NOT RUN ("motion prohibited in this session").

## 6. Record results and decide acceptance

Create a dated results file beside this handoff (or in the site's test record):

| Test ID | PASS / FAIL / NOT RUN | Revision + profile + mission | Load | Evidence paths | Measurement / deviation |
|---|---|---|---|---|---|
| A01 | NOT RUN | | | | |

Add one row for EVERY matrix ID, even if not run: the 49 motion-matrix IDs
(A01-A12, B01-B06, C01-C10, U01-U08, E01-E13) and N01-N14, 63 in all. A no-motion
session names, in the deviation column of each NOT RUN motion ID, the Phase N case
that covered part of it. Attach the final profile,
mission file and measurement table for four arrival windows, two shared zone
limits, clearance timing, stopping limit and exit-placement margins. Record why
each margin was chosen. Any profile, mission, speed or tag-placement change
affecting those values requires
repeating the related measurements and cases.

Acceptance requires the offline suite passing without exceptions, completed
physical route/stop/speed tests, measured and enabled guards, successful
controlled missed-station/missed-exit tests, and an explicit list of any
unexecuted tests. Guard software plus guessed distances is not acceptance.
If actual estimator error or repeated-tag ambiguity cannot support useful
windows, stop and propose independent station/segment identification or better
odometry. Do not widen limits until errors disappear and call that a fix.
