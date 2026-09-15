# Hardware test run sheet

Status: **all 63 cases NOT RUN** (49 motion-matrix cases and N01-N14). This
sheet sets the order in which to run them. The procedure and pass criteria for
each ID are in [route-hardware-acceptance.md](route-hardware-acceptance.md),
which is the authority. Record results as described in its section 6.

## Pick the session type first

| Session | When | Runs | Order |
|---|---|---|---|
| **No-motion** | Hardware connected, motors must not turn; arming and disarming allowed | Phase N plus A01, A02, A06, E02 | [No-motion session](#no-motion-session-motors-must-not-turn) below |
| **Motion** | Operator present, clear area, motion approved case by case | Phases A, B, C, U, E | [Execution order](#execution-order) below |

Never mix them. A no-motion session never presses Start in AUTO with `dry_run`
false, never presses Start in MANUAL with a plan or U-turn set on `/blind`, and
never opens `/manual`.

## Why this order differs from the handoff's phases

- The differential U-turn (`0030` cw, `0031` ccw) **replaces both balloon
  loops**. Every full-lap case (A05, A10, A11, C09, U07) therefore drives through
  two U-turns. Phase U must pass before any of them.
- U01 (encoder scale) is an unverified assumption in the software. No pivot runs
  until it passes.
- A06 (`tag_clear_s`) affects every station, speed and U-turn read, so it runs
  while the vehicle is still stationary.
- In the current route, U-turn tags sit on the normal-speed legs 3 -> 4 and
  1 -> 2, so a U-turn is always entered at normal speed. Treat the "from high
  speed" part of U04 as N/A unless tag placement changes. The trailer part is
  still required.

## Stop rules for every motion case

- Stop the session and do not proceed if any of these happens:
  - behaviour differs from the pass criteria in a way that could repeat unsafely
  - the vehicle or trailer leaves the agreed clear area
  - a fault message does not match the injected cause
- Never mark a case PASS from offline or simulated results.
- Change the profile or mission file only while stopped at point 2, then restart
  the process. Save a copy of both with each case's evidence.
- One process owns the CAN bus. Do not start `main.py` alongside the service.

## Step 0: physical prerequisites (before connecting)

| Check | Why |
|---|---|
| `0030` and `0031` are fixed at the line ends, beyond the station tags. Record which end has which, and why that direction has clearance | Pivot direction is set by the tag value, not by the end |
| Tape continues past each U-turn tag for at least 0.4 m, plus the reader-to-MLS offset, plus margin | The vehicle stops 0.4 m past the read while still following tape. Running off the tape end faults the U-turn |
| A clear circle around each pivot point covers the tractor's corners and the trailer's swing | A pivot sweeps the full body. The trailer response is unknown until U04 |
| Station, speed and U-turn tags are placed as in the handoff route map | Tag values repeat; only the order identifies stations |
| The operator is at the panel, the E-stop has been checked, and the test area is marked | All motion goes through the physical panel |

## Step 1: agent preparation (no motion)

- Do handoff section 4, items 1-4:
  - record the revision, git status, profile and mission file
  - run `tests/run_all.py` on the target interpreter. Expect exit 0 and the pinned count of 1516
  - check `autopilot.dry_run`. A no-motion session leaves it `true`; set it
    `false` only after A02 passes in this session
  - verify the systemd unit's working directory, profile and mission (including
    any `AGV_PROFILE` / `AGV_MISSION` environment); `/params` shows both
  - save `/api/config`, `/api/state` (without `hb=1`) and `/api/events`
- Set the starting mission. Route, speed and guard keys are in
  `missions/gy-demo.json`, not the vehicle profile. A mission change is a
  commissioning change: record the file with each case.

| Setting (mission file) | Phases 1-4 value |
|---|---|
| `route[].high_speed_to_next` (points 2 and 4) | `false` |
| `route_guard.enabled` | `false` |
| `u_turn` | `0030` cw, `0031` ccw |
| Load | Unloaded until phase 4b |

## Execution order

### Phase 1: stationary (vehicle does not move)

| # | ID | What | Output needed later |
|---|---|---|---|
| 1 | A01 | Node IDs, links, panel DI labels, and Start/Reset/selector one at a time | — |
| 2 | A02 | Magnet under the MLS in dry run: error sign and steering sign | Confirms the centring direction the U-turn relies on |
| 3 | U01 | Wheels raised: logged encoder scale versus `6064h` over marked wheel turns | Counts per wheel turn, within 1%. **Gate for all U-cases** |
| 3a | E01 | Wheels still raised: blind-run pulses segment of one wheel turn per drive | Confirms the same scale by commanded motion |
| 4 | A06 | Hand-held tag: read-gap distribution, clearance, and two identical tags | Measured `tag_clear_s`. Update the profile before any motion |
| 4a | E02 | IMU box with the MLS streaming; tilt slightly | IMU available or the reason it is not; MLS firmware |

### Phase 2: controlled straight, low speed, unloaded

| # | ID | What | Output needed later |
|---|---|---|---|
| 5 | A03 | MLS silenced during motion: sensor-loss hold, then the 2 s resume | — |
| 6 | A08 | Line-loss hold and drive-enable/ETO hold with the operator | Recovery behaviour understood before pivots |

### Phase 2b: blind run on a clear, marked floor, unloaded

Encoder accuracy comes before the U-turn pivots and before SLAM work. Write the
tape-measured values into `logs/blind_results.csv` after each segment.

| # | ID | What | Output needed later |
|---|---|---|---|
| 6a | E03 | Every start/stop interlock, including closing the browser mid-run | All stop paths verified before longer moves |
| 6b | E04 | Straight 1 / 3 / 5 m, forward and reverse, 3 runs each | Effective wheel diameter |
| 6c | E05 | Pivot 90 / 180 / 360°, CW and CCW, 3 runs each | Effective track width; cross-check for U02 |
| 6d | E06 | Arcs R = 1 m and 2 m, 90° left and right | Arc accuracy |
| 6e | E07 | UMBmark 4 m square, CW and CCW, 5 runs each | Systematic odometry errors |
| 6f | E08 | 3 m at 0.1 / 0.3 / 0.6 m/s | Speed dependence |
| 6g | E09 | Stop precision across all runs so far | Stop-error distribution |
| 6h | E11 | Off-tape run | Pure blind behaviour |
| 6i | E12 | Loop timing and bus load from the blind CSVs | Whether SYNC/TPDO3 feedback is needed |

### Phase 3: U-turn commissioning, unloaded, controlled area at each end

| # | ID | What | Output needed later |
|---|---|---|---|
| 6j | E13 | `/blind` U-turn 90 / 180°, CW and CCW, from rest on tape; Start refused without tape | Pivot and centring seen from rest before the first tag-triggered U-turn |
| 7 | U02 + U08 | First U-turn at each tag. Watch low-speed centring (75 r/min) closely | Stop distance, `u_turn_deg` at the end, final MLS error, settle time |
| 8 | U03 | MLS track level at the start and on reacquisition, both ends | Measured `u_turn_level_tolerance` |
| 9 | U05 | Far tape obscured: fault by `u_turn_max_deg` | Fault text and stop behaviour |
| 10 | U06 | Hold mid-pivot (faults), Reset mid-pivot (quiet cancel) | — |

- If U08 shows stalling or hunting, change `auto_u_turn_rpm` or
  `u_turn_center_kp_rpm_per_mm`, then repeat U02 before moving on.

### Phase 4a: normal-speed route, unloaded

| # | ID | What | Output needed later |
|---|---|---|---|
| 11 | A04 | Start then Reset within 0.6 s at points 2, 3 and 1 | — |
| 12 | A05 + U07 + A11 | Two full laps, including both U-turns. The display is read from the viewing position | Stop order, lap count, own-tag pass-over ignored once, HMI legibility |
| 13 | A07 | Reset/restart mid-leg, MANUAL/AUTO, process restart at point 2 | — |
| 13a | A12 | Restart with the empty mission, plain line-follow; restart with gy-demo, one lap | Basic auto works with no mission; gy-demo restores the route |
| 14 | A09 | Bench branch fixture with temporary tags; restore an empty `branch_latch` afterwards | — |

### Phase 4b: load and trailer

| # | ID | What | Output needed later |
|---|---|---|---|
| 15 | U04 | U-turns with the operational trailer, both ends | Trailer swing inside the clear area, or a stop decision |
| 16 | A10 | Repeated loaded laps with marked leg lengths versus the logged estimate | Four arrival windows (`min_m`/`max_m`) |
| 16a | E10 | Repeat E04, E05 and E07 with the trailer | Load effect on diameter, track and slip |

### Phase 5: speed and stopping (restore high speed on legs 2 -> 3 and 4 -> 1 only)

| # | ID | What | Output needed later |
|---|---|---|---|
| 17 | B01 | Speed entry/exit on both blue segments, both directions | — |
| 18 | B02 | Normal -> high -> normal transitions, including an exit mid-acceleration | Transition time and travel |
| 19 | B04 | Normal and high approach stops, unloaded then loaded | Measured `station_decel_limit_rpm_s` |
| 20 | B05 | Entry/exit-to-bend distances, both segments, both directions | Two `high_speed_max_m` limits |
| 21 | B06 | Read gaps at high speed | Confirms or revises `tag_clear_s` |
| 22 | B03 | Only if slow-zone fixtures are used | — |

### Phase 6: guards enabled and fault injection

Fill every `route_guard` value from phases 4b-5, then enable the guards.

| # | ID | What |
|---|---|---|
| 23 | C01 | Mission-file validation, both valid and deliberately invalid copies |
| 24 | C02 | Extra early station tag is rejected |
| 25 | C03 | Missed station read, each leg, with a clear fault area |
| 26 | C04 | Missed speed exit, each direction and segment |
| 27 | C05 | Hold or Reset mid-zone, and an expired zone |
| 28 | C06 | RFID interrupted in transit, including a rapid reconnect |
| 29 | C07 | One drive's speed feedback suppressed (bench) |
| 30 | C08 | Control sampling gap over 0.6 s (bench) |
| 31 | C10 | Watchdog, with the observer read-only and the auto browser state controlled |
| 32 | C09 | **Final:** full normal and high-speed cycles with operational loads |

## No-motion session (motors must not turn)

Hardware is connected, but no motor may turn. Arming (selector MANUAL, or a
dry-run AUTO Start) and disarming are allowed. The rules, the table of what can
turn a motor, and every procedure are in the acceptance doc's Phase N. Read
them before Step N1.

### Step N0: physical prerequisites

| Check | Why |
|---|---|
| E-stop within the operator's reach and tested | The stop if a motor ever turns |
| Drive wheels raised or chocked where possible | A second barrier; it does not make motion allowed |
| Vehicle location recorded: on the service tape, or off it | Off the tape, a loose tape strip under the MLS is needed for dry-run cases; A02 and N07 need it off the tape |
| Hand-held tags: `0010`, `0011`, `0020`, `0021`, `0030`, `0031`, and a second `0010` | N04-N06, N08, N12, A06 |
| Reader and DIO network cables reachable to unplug and replug | N05, N08, N09, N14 |
| Nobody opens `/manual` on any device for the whole session | Arrow keys on that page jog the wheels |

### Step N1: agent preparation (no arming)

- Record the revision, `git status --short`, a patch of local changes, and the
  profile and mission files.
- Run `python3 -B tests/run_all.py`. Expect exit 0, 1516 checks, no uncaught
  thread exceptions.
- Check the unit's working directory, `AGV_PROFILE` and `AGV_MISSION`
  (`systemctl cat agv_controller.service`).
- Save `/api/config`, `/api/state` (no `hb=1`) and `/api/events?since=0`.
- Start an `/api/state` poll that records `target`, `nodes[*].rpm`,
  `nodes[*].state`, `armed`, `mode`, `dry_run` and `blind.plan` for the whole
  session.

### Order

| # | ID | What | Needs before it |
|---|---|---|---|
| 1 | N01 | `dry_run` true, restart, confirm | — |
| 2 | A01 | Panel inputs one at a time (Start in AUTO is a dry-run Start) | N01 |
| 3 | N02 | MANUAL arm and disarm, encoder scale event, web stop surfaces | — |
| 4 | E02 | IMU box while the MLS streams | N02 armed |
| 5 | N10 | E-stop with MANUAL armed | N02 |
| 6 | N11 | `/blind` page: SET, replace, CLEAR, then Start with no plan | A restart first, for step (1) |
| 7 | A06 | Hand-held tag read gaps and clearance | — |
| 8 | A02 | Magnet sign check, only if the vehicle is off the tape | N01 |
| 9 | N03 | Dry-run AUTO run: drives never enabled | N01 |
| 10 | N04 | Logical route lap with hand-held tags, and the `/auto` wording | N03 |
| 11 | N05 | High-speed zone logic | N04 method |
| 12 | N08 | RFID link loss, guard off | N05 |
| 13 | N06 | U-turn tag in dry run | MANUAL arm since the last restart |
| 14 | N07 | Line-loss hold, only with a loose strip | N03 |
| 15 | N09 | DIO link loss, `/auto` closed then open | N03 |
| 16 | N13 | Mission validation in a scratch folder | — |
| 17 | N12 | Empty mission, then restore gy-demo | N01 |
| 18 | N14 | Guard with the placeholder mission, then restore | N01, N13 |

- **After A06:** propose a `tag_clear_s` change if the data supports one, and
  apply it only with the operator's agreement.
- **Stop the session** if any `target` or wheel rpm leaves 0, if a drive shows
  Operation enabled during a dry-run AUTO run, or if a fault text does not
  match its cause.

### Closing state

- Selector AUTO, disarmed, no fault latched.
- `/api/state` shows `blind.plan` null.
- Profile `mission` is gy-demo; `missions/` holds only the original files.
- `dry_run` is left `true`, and this is recorded. The next motion session sets
  it false only after A02.
- Every motion-matrix ID is NOT RUN ("motion prohibited in this session"),
  naming the Phase N case that covered part of it.

## Measurements this sheet must produce

| Value | From | Key (`route_guard.*` in the mission file, the rest in the profile) |
|---|---|---|
| Encoder counts per wheel turn | U01 | None; confirms the arming-time scale |
| RFID repeat clearance | A06, B06 | `rfid.tag_clear_s` |
| U-turn reacquisition level margin | U03 | `autopilot.u_turn_level_tolerance` |
| Centring speed and gain, if changed | U02/U08 | `auto_u_turn_rpm`, `u_turn_center_kp_rpm_per_mm` |
| Four arrival windows | A10 | `route_guard.legs[]` |
| Station deceleration limit | B04 | `route_guard.station_decel_limit_rpm_s` |
| High-speed zone limits | B05 | `route_guard.high_speed_max_m` |
| Effective wheel diameter and track width | E04, E05, E07 (E10 loaded) | `vehicle.wheel_dia_m`, `vehicle.track_m`, only after the evidence supports a change |

A result sheet needs one row for each of the 63 IDs: A01-A12, B01-B06, C01-C10,
U01-U08, E01-E13 and N01-N14, including any that were not run and why.
