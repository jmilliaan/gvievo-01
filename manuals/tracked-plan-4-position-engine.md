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
| F7 | **1 or 2 MRU machines per trip** (`trip_calls`; 1 since 2026-11-05, `manuals/station-call-plan.md`) | D18 |
| F8 | **Operator confirmations, not sensors:** trolley released (Start at the release stop), trolleys off at home. Superseded with `station.enabled`: the rear lidar decides (`manuals/station-call-plan.md`) | D10 |

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
| ~~`zones`~~ | retired 2026-10-25 | high-speed zones are **areas drawn on the map** (section 10), not mission data |
| `trip_calls` | 1 since 2026-11-05 (exists) | F7: 1 or 2 |

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
| zone [S_a, S_b] | where the route runs inside a high-speed area | `areas.json` of the map revision |

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
- **`tape_loc.lost_fault_s` is still not acted on.** Section 11 replaced what it was for.

Floor order from here:

1. Roles and positions (done 2026-10-25, section 10). Left: HOME-N (Teach here at standstill), the
   high-speed areas. Build, Publish, Make active.
2. E2: five Guide-page laps, with the shadow log against the floor (runbook 3.5 item 4).
3. `colcon build --packages-select amr_interfaces`, then `tape_loc.live: true` and a restart, once
   E2 passes. Then E3 (one-call trip), E4, E5.

## 10. 2026-10-25: roles, areas, offset marks

The operator's role table for M1–M15 (the table itself is in
`documentation/layout-reference/tape-graph-g1/README.md`):

| Decision | Change |
|---|---|
| High-speed zones are **areas** drawn on the map, not mark pairs | Mission `zones` refused by name. `<teach>/areas.json` is written by the `/tape-areas` page (engineer). `trip_route.area_ranges` cuts the route where it lies inside an area for at least 1 m. The runtime reads the areas fresh at each trip's Start. The shadow lap logs entry and exit |
| ME-1…ME-4 (attach full) = 2 m from MW-1…MW-4 toward home | Teach action `mark_offset <M> <metres> [<new M>]`: a mark on the tape the other way through the reference mark (`tape_teach.offset_mark`), + = the inbound travel direction. Teach page "Inbound at offset" |
| UT-MRU1…3 = 1.4 m from MW-1…MW-3 toward the line's end; MRU4 turns at the tape end | Teach action `mark_along`: the same along the reference mark's own tape. `uturn_points` UT-MRU1…3 (cw) and the machines' `uturn` in `site-103.json`; MRU4 has none. (A first answer made the old M12 UT-MRU4; the updated rules replaced it, and the mark is deleted) |
| STU (left at J-N) | later |

On the vehicle (backup `marks-2026-10-25-0954.bak.json`):
- M3, M4, M6, M7 deleted;
- labels from the table;
- M12–M15 by `mark_offset +2.0`, M16–M18 by `mark_along +1.4`;
- stations.json: ATT=M1, MW-1…4=M8…M11, ME-1…4=M12…M15, UT-MRU1…3=M16…M18, each checked
  against g1's legs and directions;
- all ten MRU trips compile on g1 (HOME-N stood in by the pass start for the check). On a mid-line
  trip the take-back stop comes 3.4 m after the pivot.

Images: `documentation/layout-reference/tape-graph-g1/marks-*.png`, redrawn 2026-10-25.

Still to teach: HOME-N (Teach here at standstill), the high-speed areas. Then Build → Publish →
Make active (g2).

2026-10-25 (operator): `tape_loc.sigma_station_m` 0.025 → **0.05 m**, the validation's ceiling.
2 sigma is then the whole ±10 cm budget, and the stop's own error comes on top. The operator
accepts that in exchange for fewer `position` holds before stations.

2026-10-25 (operator): **MRU inbound, always branch left until HOME.** J-ML and J-SPLIT were already
`left`. The J-STEM merge gets `"steer": "left"` in C-MRU: a merge may name a side, armed before it
like an order (`trip_route.side_at`), while its leg keeps the name `J-STEM:merge>J-SPLIT`, so g1 stays
valid. All ten MRU trips arm right@J-N, then left@J-ML, left@J-STEM, left@J-SPLIT, each with the full
1 m before its fork. The shadow lap logs the J-STEM order too. C-BTU's J-STEM is unchanged.

2026-10-25: **C-BTU taught next** (operator: for AGV-01 all of row 2 is laid, BTU9–16 and BTU17–24;
BTU1–8 belong to the other AGV).
- The C-MRU lap of 10-24 saw no fork on the trunk between J-ML and the MRU line, so J-R2E is not
  where `site-103.json` puts it (M5: BTU's return joins at J-ML).
- The C-BTU topology in the mission (J-S, X2, J-LV, J-R2E) is therefore fitted to the recorded
  lap's fork episodes before any Build, not guessed.
- For the lap: mission `c-btu-guided` (guided, 0.4 m/s, no marker run: ends with Reset at
  HOME-N). Marks off every built leg are kept at their AMCL pose and placed at Build.

## 11. 2026-11-06: AMCL corrects, it has no veto

First floor trip, MRU4, 10:59: AMCL 12 cm off the taught path among moved trolleys, the MLS on the
tape throughout. Five rejected poses meant LOST, and the trip held 0.4 m short of ATT. Start could
not clear it: re-acquiring needs poses, AMCL is silent at rest, and Start would not move while LOST.
Owner's rule: two sensors exist so that one being wrong does not stop the vehicle, and branching
must not fail.

| Case | Before | Now |
|---|---|---|
| `lost_rejects` in a row, readiness leaving READY, sigma over `sigma_lost_m` | LOST, every decision holds | `amcl_out`: S goes on from wheels and tape, sigma grows. Two poses in a row that agree and pass the gates bring AMCL back, with no operator |
| Stop | HOLD over `sigma_station_m` | Stops at the best estimate, logged with its sigma |
| Tape-end U-turn | HOLD over `sigma_junction_m` | Goes on: the tape end is on the floor. S and sigma reset there |
| Order | Armed `junction_lead_m` before the fork, HOLD over `sigma_junction_m` | Armed `max(lead, 3 sigma)` before the fork, or at once on a fork seen before that. Used by a fork well before its own: armed again; if no other fork comes, that one was the junction. One order at a time |
| Order with no fork seen at all | FAULT past 1 m | FAULT past `max(1 m, 3 sigma)` |
| Mid-line U-turn | HOLD over `sigma_station_m` | HOLD once over `sigma_junction_m`: a released trolley may be close; the operator's Start pivots |
| HIGH | Needs sigma | Needs sigma and AMCL in |
| LOST | Many causes | A wrong branch only (`_wrong_branch_check`, while READY): FAULT |

Branching needs no AMCL: an order acts at the next fork the MLS sees, so S only has to get it
standing in time, and each fork re-syncs S. With AMCL out on the 76 m from the tape end to J-ML, the
model gives sigma about 0.8 m and a 2.4 m window. A stop that far along is only as good as the wheels:
an MLS marker before the MRU stops is the fix if that accuracy is needed without AMCL.
`max_lateral_m` is worth raising after a trip's log: a pose off sideways still knows along-track.

### 11.1 The same day: the wrong lane, and how a run is seen now

Trip 11:25-11:35, MRU4 and back: every stop at about the right distance, then HOME-N on the **south
bay**, 1.26 m to the right of the taught north bay, reported "served". J-SPLIT was ordered left and the
order stood through the whole fork. Stops are a distance, and the two bays are about the same length,
so the distance was right on the wrong tape. Why the fork went right is **not known yet**: the flight
recorder keeps 15 s, and its next dump came 39 s later. What caught it was the operator.

| Added | What it does |
|---|---|
| `site_run.ForkWatch` | Each ordered fork, from the MLS alone: of the ordered side's track and the other, which one stays when one track is left. The other: FAULT at the fork. A merge closing up, a double reading or a crossing is "unjudged". `branch.unhonoured` cannot say this: it fires on correct forks too |
| `tape_locator._wrong_lane_check` | AMCL 0.5-8 m off, one side, for 1.5 m of travel, within 12 m past an ordered fork: FAULT, READY or not, taught other leg or not. Small errors and an AMCL that is simply far away still have no say |
| `amr_line.trip_log` | Every tick, AMCL pose with its verdict and lateral, readiness, event and fork of a run, `<state_dir>/logs/trip_log/*.jsonl.gz`, about 2 KB/s (1.3 MB a 660 s trip), newest 60. Written off the control thread; only tick-rate rows can be dropped, counted in the end row |
| `tools/trip_report.py` | The run on a page; `--fork J-SPLIT` tick by tick |
| Flight recorder | A dump after each ordered fork, with S, sigma and the order's intent |

These stop a wrong tape; they do not make the fork right. That needs the J-SPLIT ticks of the next
run: slower through ordered forks, or steering toward the ordered side before the split, are the likely
fixes. The 0.5 m and 1.5 m are provisional until a trip's `AMCL by leg` table shows the real spread.

The first trip log (12:12) showed at once: 177 of 320 poses refused as "waiting for a second pose",
because two poses were compared by position, which a moving AGV changes between them. Now by the
offset from the wheels. It also kept HIGH off, as HIGH needs AMCL in. A real fork read well: J-N,
ordered right, kept -63 mm, other +118 mm, one track at -65 mm, "ordered".

### 11.2 The next run, 12:12: a false "drive link" stop, and no HIGH

- **"drive link standby" at S 52, and at 11:26 and 11:17 before it: not the drives.** `drive_node._loop`
  samples `now`, serves requests, then compared it with the panel's receive time. A message taken
  in between is "from the future", which `arm_policy` refuses as stale. One such tick powered the
  drives down (about 0.45 s of disarm) under a running vehicle. The panel was fine: its real limit
  is 1 s, and the mux, on a shorter one, never saw a gap. `_update_power` now samples `now` after
  the read. From the code and the timing, not reproduced: a later "panel state stale" is a real gap
  and would disprove it.
- **No HIGH:** every running tick of the zone had `amcl_out`, the veto added in section 11. HIGH now
  goes by sigma alone (`sigma_junction_m`). With AMCL out, sigma reaches that 15-20 m after a re-sync,
  so the long MRU zone still gets little until AMCL is usable there: 3 of 133 poses past S 33 were used.
- The trip log's `field_clear`, `auto` and `link` were empty (`job._i` is only set with calling on);
  it now has them, and `high`, `high_why` and `zone`, and the report totals the zone time by reason.

### 11.3 13:56, MRU1: why J-SPLIT goes right (found, supersedes the guess in 11.1)

The trip log has it. **The J-SPLIT anchor was on the wrong fork.** At the taught J-SPLIT (-10.59, -0.31)
the two tracks close up, -123 to -3 mm: a merge. It used the order. The real split is 5.1 m on, where
they open, [-1, 7, 16] to [-56, 105] mm, with nothing standing, so the follower kept the nearest track:
the south bay. The teach pass shows the same fork at 206.42-206.61 m, under "not junctions", and the
11:35 trip logged it as "fork with no taught junction near S 217.73". On the pass the engineer armed
left by hand just before it. Steering was not the cause.

`anchors.json` J-SPLIT moves to the pass's position at the fork's end, (-5.545, -0.393); the old file is
kept as `anchors-2026-11-06.bak.json`. Graph g3: `J-STEM:merge>J-SPLIT` 6.66 m, `J-SPLIT:left>J-BMERGE`
8.66 m, HOME-N at s 5.75 m. The merge still arms and uses the order first, which logs "a fork ... before
J-SPLIT used the order: armed again". `ForkWatch` no longer calls a fork a crossing for opening on three
tracks. Everything else on this run worked: every stop to about 5 cm by the locator, the mid-line U-turn,
J-N, J-ML, J-STEM, 97 s of HIGH, and the wrong-lane check stopped it 2.4 m past the split.

### 11.4 14:26, MRU1: J-SPLIT right, and a stop for one bad DIO reply

The anchor fix held: left at the real split, fork watch "ordered" (tape to +98 mm of the sensor's
range, so thin). At S 105.9 the DIO module answered one coil read with a Modbus exception: connection
dropped, 0.5 s reconnect wait, panel invalid, HOLD, back on Start. `DioLink` now retries a failed scan
once at once on a new socket; a second failure is lost, as before. No image gets older than it may
be: the retry publishes only on success and `panel_io.source_fresh` has its own limit (0.2 s). Each
retry is logged as a `PANEL` warning with its reason and counted. Why the module sent that reply is
not known; a Wi-Fi driver register dump fell in the same second, which may be chance.

### 11.5 Home moves to the right bay, HOME-N2 (operator, 2026-11-06)

`site-103.json`: home HOME-N2 on `J-SPLIT:right>J-BMERGE`, J-SPLIT order right, in both circuits. The
merge is a node, J-SMERGE (anchor at the old J-SPLIT position): an armed order is otherwise allowed
there, and RIGHT would take the joining tape at -122 mm. The north-bay passes are in
`<teach>/passes-north-bay` and the anchors in `anchors-north-bay.bak.json`: a pass is split by the
mission's circuit, so an old lap would file its left-lane points under the new right-lane leg.

**No lap (operator's call): g4 is drawn.** `J-SPLIT:right>J-BMERGE` is a polyline from the operator's
sketch, checked against 48 logged AMCL poses on that lane (median +3 cm, worst 10 cm). J-STEM to J-SPLIT is
cut from g2 and g3, so it is the 10-24 pass. The left-bay leg stays in the graph: it gives the wrong-branch
check something to compare with. HOME-N2 at (0.04, -1.228) is beside HOME-N by position, not taught.
**Do not press Build on this graph:** `passes/` is empty, and Build makes a graph from passes only. A
later recorded lap from HOME-N2 replaces the drawn leg. Back to the north bay: restore those two
and the mission, and activate g3. The station contract's examples still say HOME-N
(`amr_station/test/contract.py` renames for them); to settle with the station side before P9.
