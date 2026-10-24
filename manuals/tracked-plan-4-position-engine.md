# Tracked plan 4: the position engine (stops, orders, U-turns and zones by position)

Status 2026-10-24 (evening): **E0, E1 and the code of E2/E3 built, uncommitted, offline suites
green; `tape_loc.live` is false**, so nothing drives by position yet. Floor work left: roles for
M1–M12, the inbound/U-turn marking lap, E2 laps, then live (section 9). Builds on tracked plan 3
(P1 built and running in shadow: graph g1 taught, locator, route compiler, `trip.py`). This is
plan 3's P2 and the engine half of P3, reshaped by the decisions of 2026-10-24 (site-layout-103
D15–D19).

## 0. What is asked (operator, 2026-10-24)

| # | Function | Source |
|---|---|---|
| F1 | **Stop, then continue on panel Start** at machines and ATT. MRU machines have two stops: OUTBOUND (home → machine, trolley released) and INBOUND (machine → home, trolley attached), at different spots | D17 |
| F2 | **End-of-cycle stop** at HOME-N | D11 |
| F3 | **Branch orders from the destination**, armed before each diverge. No marks: from the taught junction positions | D15 |
| F4 | **High-speed zones as position ranges** (no set/reset strips, no latching) | D19 |
| F5 | **U-turns:** at the tape end (code 3, U-MRU) and **mid-line after the last release**, at that machine's U-turn mark | D16 |
| F6 | **Automatic slow-downs** before every stop, U-turn, junction and zone exit | operator |
| F7 | **1 or 2 MRU machines per trip** (`trip_calls`, 2 now) | D18 |
| F8 | **Operator confirmations, not sensors:** trolley released (Start at the release stop), trolleys off at home | D10 |

Out of scope: trolley detection, BTU (row 2 not laid), the open issues (scan-stale LOST,
weak tape at the MRU end).

## 1. Why branch orders by position are safe (D15)

The order does not need a precise position, only **which junction comes next on the trip's
route**:

- The route is a sequence. The order for the next diverge is armed after the previous
  junction was passed, exactly as the engineer does on the Guide page today.
- Every junction passed is an MLS fork episode that **resyncs** the locator (plan 3 D8).
  Between junctions, wheel travel carries S with ~1 % error. AMCL only has to agree
  which leg the AGV is on (legs are 1.5–76 m long).
- **No silent pass (plan 3 D5):** if the locator is not healthy (sigma > 0.20 m) by
  `S_fork − 1.0 m`, the AGV HOLDs before the fork, not after it.
- **Wrong branch → FAULT** within `wrong_branch_window_m` (3 m): the locator compares the
  AMCL path with the expected leg (already built, `tape_locator._wrong_branch_check`).
- **Evidence before trust:** in shadow mode (E2) the engine logs "would order RIGHT at J-N"
  on every lap while the Guide page still drives. Live only after N laps agree with it.

## 2. Data: from marks to a trip route

### 2.1 Taught positions (vehicle, per map revision)

Marks (`marks.json`, M1…Mn) become named points with one Teach action:

    mark_role M6 MW-1          -> station MW-1 (pose of M6) in stations.json

The existing station machinery then applies unchanged: Build re-projects every station onto
its leg, compile_route checks they lie on the circuit in order. The mark keeps its pose, so a
re-taught leg moves the station with it.

### 2.2 Designed data (repo): `missions/site-103.json`, schema site-3 → site-4

| New item | Example | Meaning |
|---|---|---|
| `uturn_points` | `"UT-MRU1": {"direction": "cw"}` | a mid-line U-turn point: a station-like taught position on the outbound leg |
| group machine `uturn` | `"MRU1": {"release": "MW-1", "take": "ME-1", "uturn": "UT-MRU1"}` | where the trip turns if MRU1 is its farthest release |
| `zones` | `"Z-TRUNK": {"from": "ZA-TRUNK", "to": "ZB-TRUNK"}` | HIGH between two taught points on the same route, in travel direction |
| `trip_calls` | 2 (exists) | F7: 1 or 2 |

Loader refusals (each a test in `tests/test_mission.py`, `EXPECTED_CHECKS` updated): a machine
`uturn` that is not a `uturn_points` id, a zone whose ends are not taught points, a zone end
before its start, a U-turn point before its machine's release stop (checked at route compile:
taught positions are vehicle data).

### 2.3 The trip route (`amr_line/trip_route.py`, new, pure)

`compile_trip(trip, mission, graph) -> TripRoute`: one S axis for the whole trip.

1. Outbound: home leg → … → the MRU line leg, **cut at the U-turn**:
   - the farthest called machine's `uturn` point (D16), or
   - U-MRU (tape end) if that machine has no U-turn point (the fallback).
2. Inbound: the return leg **entered at the projection of the U-turn point** onto it (the
   two directions of one tape are two legs; `tape_graph.Polyline.project`), then → … → home.
3. Events on that S axis, sorted:

| Event | S | From |
|---|---|---|
| stop (attach, release, take, home) | station S on its leg | trip plan (`trip.Trip`), stations |
| order (left/right) | `S_fork − junction_lead_m` | route nodes, the leg's `order` |
| junction resync | `S_fork` | route nodes |
| U-turn (midline / tapeend) | U-turn point S, or the leg end | 1. above |
| zone [S_a, S_b] | the zone's two points | mission `zones` |

`trip.Trip` changes: `may_pivot()` checks the releases **up to the U-turn** (all of them, since
the U-turn is after the last release); the plan gets the per-machine U-turn point.

## 3. The engine (`amr_line/site_run.py`, new, pure, clock-fed)

`SiteRun` drives one TripRoute from locator state. It offers FollowJob the same surface as
`TapeRun` (steer, advance, stop, uturn_req/approach/begin_spin/finish_u_turn, speed, events,
fault), so `job.py`'s measured stop, U-turn pivot, kink pivot, holds and premove are reused.

Each tick, inputs: locator (S, sigma, health, lost), follower diag, wheel travel.

| Output | Rule |
|---|---|
| **speed ceiling** (F6) | `v(S) = min over upcoming events e of sqrt(v_e² + 2·a·(S_e − S))`, with `v_e` = 0 for stops/U-turns, NORMAL for zone ends and junctions, and `a` below the drives' deceleration (as `APPROACH_FRACTION_OF_DRIVE`). One envelope replaces every hand-placed slow-down |
| **zone** (F4) | HIGH while `S_a ≤ S < S_b − exit_distance(HIGH→NORMAL)`; no latching, a LOST locator means NORMAL |
| **branch choice** (F3) | from `S_fork − lead` to the resync, the node's order; STRAIGHT otherwise. Locator not healthy at `S_fork − lead` → HOLD `position` |
| **stop** (F1, F2) | measured stop at `S_stop − S` (job's existing `begin_measured_stop`), checked at braking start: sigma ≤ `sigma_station_m`, else HOLD `position` before the stop. At rest: HOLD `station`; panel Start → `trip.serve(id)`, depart |
| **U-turn** (F5) | approach on the envelope; at the point: stop, then `trip.may_pivot()` (else HOLD `payload`), then the pivot. Mid-line: the spin starts **with the tape under the sensor** (new UTurn start state: leave the tape, then reacquire past the gyro gate). Tape end: as today (code 3 kept as the fallback trigger) |
| **end of cycle** (F2) | HOME stop → DONE; `Payload.trip_ended()`; the next trip's Start needs "trolleys off" (F8) |

What stays from the marker engine: the kink pivot, the post-U-turn search, the junction burst
filter (code 3 at the tape end only), Continue on Start, the flight recorder.

## 4. Wiring (node, web)

| Piece | Change |
|---|---|
| `tape_runtime` | the locator runs on the TRIP route (not the shadow circuit); exposes `(S, sigma, health)` per tick |
| `job.py` | `_new_tape()` builds `SiteRun` for a trip, `TapeRun` otherwise; Inputs gain the locator state |
| `line_follow_node` | services: `call`, `cancel`, `confirm_released`, `confirm_off`; LineState: trip, next stop, S/sigma (**`amr_interfaces` → colcon build**) |
| Calls page (P3, new) | queue, the formed trip, confirm buttons. Engineer and operator. Nothing on it starts motion (D14) |
| Run page overlay | the trip route and the next event drawn over the map |
| profile | `tape_loc.live` (false = shadow, true = drives); schema, validation and refusal test |

## 5. Steps

| Step | Content | Done when |
|---|---|---|
| **E0** Roles | `mark_role` action; site-4 schema (uturn_points, machine `uturn`, zones) with refusals; Teach page field for roles | M1–M12 named, Build compiles C-MRU with every station |
| **E1** Route + engine | `trip_route.py`, `site_run.py`, Trip changes. Closed-loop tests on the existing World plant with a synthetic locator: one-call and two-call MRU trips, mid-line and tape-end U-turn, a zone, every hold | offline suite green |
| **E2** Shadow | the engine runs beside the Guide-page drive and logs every decision with its sigma | 5 laps: every logged order matches the Guide orders, every "would stop" within ±10 cm of the floor marks |
| **E3** Calls + live | Calls page, services, LineState (colcon), `tape_loc.live: true` | one-call trip floor test |
| **E4** Mid-line U-turn | the tape-under-sensor pivot on the MRU straight, empty | 10 pivots, all reacquired inside the gyro window |
| **E5** Acceptance | plan 3 P2 criterion | 20 MRU trips (2 calls), every stop ±10 cm, every provoked failure ends in its hold |

## 6. Failure modes and recovery

| Failure | Engine reaction | Recovery |
|---|---|---|
| Locator doubtful before a stop/order/U-turn | HOLD `position` before the point | panel Start once healthy (READY again: re-pose, confirm) |
| Wrong branch | FAULT `wrong_branch` within 3 m | MANUAL, jog back, Reset, Start |
| Release not confirmed at the U-turn | HOLD `payload`, no pivot | operator releases, Start at the release stop or confirms on Calls |
| Trolleys not confirmed off at home | trip Start refused | confirm on Calls |
| Tape lost after a mid-line pivot | the post-U-turn search (built), then FAULT | align on the tape, Reset, Start |
| A stop overshot (envelope too late) | the stop is still measured from S: it stops late, the error is logged | tune `a` on the floor |
| Graph/map mismatch | layer refuses the trip (plan 3 §2.4) | publish/activate a matching graph |

None of this is in the safety path: the engine decides where to stop and which tape to take,
as RFID did. FX3/STO, the panel's Start and the mux are untouched; every new hold is more
restrictive.

## 7. Inputs still needed

- **Roles for M1–M12**, and a marking lap for the INBOUND stops and the U-turn points.
- Pivot direction per U-turn point (cw like U-MRU unless a machine side forbids it).
- The zone ranges (which marks), once the code 1/2 strips are retired.

## 8. Reference images

`documentation/layout-reference/tape-graph-g1/`: the taught pass, the g1 legs, the junction
anchors and marks M1–M12 on the rev1 map (2026-10-24), with an index (`README.md`).

## 9. Build record (2026-10-24)

| Piece | Where | Tests |
|---|---|---|
| site-4 schema: `cruise_mps` (0.4), `uturn_points`, machine `uturn`, `zones`; site-3 refused by name | `agv_core/mission.py`, `missions/site-103.json`, `test-mru-straight.json` | `tests/test_mission.py` (+9 checks) |
| Trip's U-turn: farthest release's point, else the tape end; `CallQueue.restore` | `amr_line/trip.py` | `test_site_run.py` |
| Trip route: cut, return entry, stops, nodes (mirror), events, zones, refusals | `amr_line/trip_route.py` (new) | `test_trip_route.py` (9) |
| Engine | `amr_line/site_run.py` (new, a `TapeRun`) | `test_site_run.py` (16, closed loop) |
| Job: site mission as a job, trip at Start (calls put back if refused or cancelled), holds `position`/`payload`, `at_rest()`, trip aborted on FAULT/Reset/Clear/tape lost | `amr_line/job.py`, `tape_run.py` hooks | `test_site_run.py` |
| Locator: mid-line U-turn mirrors S about the node | `tape_locator.py` | `test_trip_route.py` |
| Runtime: `mark_role`, `roles`, `begin_trip`, `loc_state`, points and zones in the shadow lap (E2) | `tape_runtime.py`, `tape_teach.project_station`, `tape_graph_store.save_stations` | `test_tape_runtime.py` (+3) |
| Node: `/amr/line/trip` (LineTeach: call, cancel, confirm_released, confirm_off, status); live → site mission is the job at start | `line_follow_node.py` | - |
| LineState `trip`, `trip_next`, `trip_queue`, `trip_payload` | `amr_interfaces` (**colcon build**; the node skips the fields until then) | - |
| Calls page (operator and engineer), `/api/line/trip`, site lists with machines and points, the site mission in the Run-tracked picker when live, the Teach page's Role field | `amr_web` | `test_teach_page.py` (+3) |
| Profile `tape_loc.live` (false); refused without `tape_loc.enabled` | `profiles/agv-01.json`, `agv_core/config.py` | `tests/test_config.py` (+1) |
| Alarms `POSITION_UNSURE`, `PAYLOAD_UNCONFIRMED` | `agv_core/alarms.py`, RUNBOOK section 4 regenerated | `tests/test_alarms.py` |

Decided while building (they differ from sections 3 and 6):

- **No new UTurn state.** The spin already requires the tape to be lost before it may stop on it
  (`uturn.py`): a mid-line pivot that starts on the tape leaves it within ~10° and reacquires it
  past the gyro gate.
- **From rest, creep.** A stop or U-turn point reached below 80 % of the cruise (after a hold or a
  resume) creeps at 0.1 m/s to 5 cm before it, then stops measured. A measured stop solved
  while still accelerating ran 0.23 m past in the closed-loop test.
- **HOME window.** A trip's Start needs the locator within 0.5 m of HOME-N, not LOST, and sigma
  at most `sigma_junction_m`. It needs a formed trip and the trolleys confirmed off too.
- **A trip is not resumed after a FAULT** (section 6 said "Reset, Start"). Reset, a wrong branch
  or a lost tape aborts it. The log says what was served. Recovery: MANUAL to HOME-N, **At
  home**, Reset, call again. A tape lost mid-trip is a FAULT, not DONE.
- **An order still standing 1 m past its node is a FAULT**: the fork was not seen where it is
  taught.
- **Zones:** an end not taught means NORMAL there (noted), not a refusal. An end before its start
  on the trip is refused.
- **Envelope rate:** the HIGH↔NORMAL comfort rate (`high_ramp_s`), back at the cruise 0.3 m
  before every stop trigger, U-turn trigger, junction fork and zone end.
- **`tape_loc.lost_fault_s` is still not acted on**: a `position` hold waits for Start.

Floor order from here:

1. `mark_role` M1–M12 (Teach page Role field). Mark a lap for ME-1…ME-4 and the U-turn points,
   and assign them. Add the `uturn_points`, the machines' `uturn` and the `zones` to
   `missions/site-103.json`. Build, Publish, Make active.
2. E2: five Guide-page laps, with the shadow log against the floor (runbook 3.5 item 4).
3. `colcon build --packages-select amr_interfaces`, then `tape_loc.live: true` and a restart, once
   E2 passes. Then E3 (one-call trip), E4, E5.
