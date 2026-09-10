# Direction-aware route and high-speed commissioning handoff

Status: software implemented and tested offline; **all hardware tests below are NOT RUN**.
This document is for the next coding agent and the operator. No conversation
history is needed. Read the current AGENTS.md and inspect Git status first.
Use the checked-out code as the authority; `gy-demo-review.md` reviewed an older
commit and several of its findings have since been addressed. Do not restore
the old README or deploy a different revision merely to match that review.

Offline verification on the development PC, 2026-09-10: 117 test functions /
1,275 checks, exit 0, no uncaught thread exceptions, using Python 3.13.9.
Separately, `tests/browser_auto.py` ran 44 real-DOM Auto page checks at two
viewports with fixture-only HTTP, 0 failed; it starts no vehicle services.
Changed Python files also passed Python 3.10 syntax parsing. This is not a
substitute for running the suite with the deployed interpreter and dependencies.

## 1. What is being commissioned

Python controller for two CANopen wheel drives, SICK MLS line sensor, Chafon
RFID reader, Modbus physical panel, and Flask HMI. Runtime uses dedicated
threads. CAN transactions, route decisions and distance integration belong to
the CAN thread. This is not the separate asyncio/fleet project.

The track is approximately 90 m, a shared magnetic line with a balloon U-turn
at either end. Outbound goes from the lower end towards the upper end; inbound
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
`speed_switch_accel_decel_s=2` derives a 500 rpm/s rate. Existing 4000 rpm/s^2
jerk limiting stays active: this is not an exact two-second completion promise.
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
- `route_guard` adds early-arrival rejection, missed-station distance fault,
  distance limit on high-speed zones, speed-feedback freshness checks, and a
  load-time check of high-speed station deceleration against a measured limit.

Route fault recovery requires physically returning to point 2 and restarting
the controller. Reset acknowledges the operator fault but does not clear
`route.guard_error`; Start remains refused. This also applies to RFID encounter
buffer overrun and a missing station rule, even when distance guarding is off.
Ordinary Reset/manual transitions without a route fault preserve the stage.

## 3. Measurement-dependent settings: initially disabled

The supplied `profiles/agv-01.json` has `route_guard.enabled=false`. Its distance
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
   changes. Preserve the exact profile used for each test; do not overwrite
   historical run folders. Record vehicle, load/trailers, floor conditions,
   operator, date and software revision.
2. Run `python3 -B tests/run_all.py` from the repository root on the target's
   existing Python environment. On the development Windows PC the verified
   interpreter is `D:\anaconda3\python.exe -X utf8 -B tests/run_all.py`.
   Require exit 0, the check count pinned in `tests/run_all.py`, no failed
   checks and no uncaught exceptions. Do not install/upgrade vehicle packages
   just to match a developer environment. Dependencies include Flask,
   python-can, pymodbus and matplotlib.
3. Verify the deployed working directory/profile against the live service
   configuration (`systemctl cat agv_controller.service` where applicable).
   Do not launch `main.py` alongside the running service: two processes must
   not own the CAN bus. `dry_run` is not an offline simulator or a global
   manual-motion inhibit. For a stationary sensor-only test, auto dry-run
   leaves the drives unarmed; it does not make a braked shaft free to push.
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
   Restart profile changes only while stopped, at the assumed initial point 2.
   Changes to high-speed permission are commissioning-profile changes to record.

Evidence per motion case: auto CSV and PNG under `logs/NNNN-auto_*`, event
capture, before/after state snapshots, physical distance/time observations and
the profile copy. CSV now includes direction, current/next station, lap, speed
mode/target, `guard_enabled`, `guard_error`, `distance_estimate_m`, and
`high_distance_estimate_m`. The last two are estimates, not ground truth.

## 5. Hardware test matrix

All rows start NOT RUN. Run in order of the phases below. A coding agent can
collect evidence and evaluate it; tests requiring movement or physical tag/link
changes need the operator. Do not mark them passed from simulated results.

### Phase A: stationary checks and normal-speed route

| ID | Procedure | Pass / required evidence |
|---|---|---|
| A01 | Confirm node IDs (left 1, right 2, MLS 10), RFID/DIO links and live panel DI labels; check Start/Reset/selector one at a time while stationary | HMI input labels match physical controls; no unexpected motion command; correct profile/service |
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

### Phase B: controlled speed and stopping measurements

Provide sufficient clear runout and use a controlled straight before the full
route. Restore only the intended long-leg high-speed permissions. Begin
unloaded, then repeat with the intended trailer/load conditions. Stop the test
if actual stopping/steering behavior exceeds the agreed test area.

| ID | Procedure | Pass / required evidence |
|---|---|---|
| B01 | On each blue segment outbound, read 0020 then 0021; inbound read 0021 then 0020 | Entry selects high, exit normal, correct direction; reused pair works twice per long leg; both U-turn legs remain normal despite these tags |
| B02 | Measure stable normal -> high -> normal; also exit during acceleration | Nominal reference uses 500 rpm/s with jerk limiting, no reference jump; record actual duration, travel and wheel feedback. Approximately 2.06 s / 0.975 m is only an offline reference for high -> normal |
| B03 | If using slow-zone fixtures, overlap high with slow; test station stop and controlled hard stop separately | Slow wins; station rate is its own calculation; hard stop collapses software reference to zero. Actual wheel deceleration is captured, not inferred from the command |
| B04 | Measure normal and high approach stops on a controlled straight, unloaded and loaded, before allowing high near operational stations | Record tag-to-rest distances, overshoot, trailer behavior and peak/settled deceleration. Set measured station_decel_limit_rpm_s. Do not accept a mathematical 0.4 m as a measured stop |
| B05 | Measure available entry/exit-to-bend/station distances on BOTH blue segments in BOTH directions, with loaded transition data | Exit placement and shared per-direction high-distance limits leave room for transition plus estimator error before normal speed is required |
| B06 | Repeat read-gap/clearance tests at high speed and with actual tag alignment | No duplicate encounter or missed necessary station/exit read in the tested runs; document detection failures rather than discarding them |

### Phase C: guards enabled and fault injection

Fill every `route_guard` measurement, validate the profile, then enable it.
Archive both the measured data and the chosen margins. Do not use synthetic
values from `tests/test_route_guard.py`. Use a reduced-speed controlled test
area first for deliberate missed tags, then the approved loaded test conditions.

| ID | Procedure | Pass / required evidence |
|---|---|---|
| C01 | Enable guards with complete measured settings; separately try a copied profile with a missing bound or overly low station deceleration limit using offline validation | Valid profile loads; invalid profiles are refused with the offending setting. Live `/api/config`, `/params` and HMI show guard on |
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

## 6. Record results and decide acceptance

Create a dated results file beside this handoff (or in the site's test record):

| Test ID | PASS / FAIL / NOT RUN | Revision + profile | Load | Evidence paths | Measurement / deviation |
|---|---|---|---|---|---|
| A01 | NOT RUN | | | | |

Add one row for EVERY matrix ID, even if not run. Attach the final profile and
measurement table for four arrival windows, two shared zone limits, clearance
timing, stopping limit and exit-placement margins. Record why each margin was
chosen. Any profile/speed/tag-placement change affecting those values requires
repeating the related measurements and cases.

Acceptance requires the offline suite passing without exceptions, completed
physical route/stop/speed tests, measured and enabled guards, successful
controlled missed-station/missed-exit tests, and an explicit list of any
unexecuted tests. Guard software plus guessed distances is not acceptance.
If actual estimator error or repeated-tag ambiguity cannot support useful
windows, stop and propose independent station/segment identification or better
odometry. Do not widen limits until errors disappear and call that a fix.
