# Tape localization runbook: AGV-01, site 103

Status 2026-10-17. What each section needs before it can be used:

| Section | Usable |
|---|---|
| 1 Rules | now |
| 1A The straight in front of MRU | now: where sections 2 and 3 run until the plant is free |
| 2 P0 measurement | now (T1–T3 built 2026-10-18; T1 checked on a private domain, not yet on the floor) |
| 3 Teach | now: P1 teach + shadow built 2026-10-18, not yet run on the vehicle |
| 4 Daily operation | after P2 + P3 (planned) |
| 5 Holds and faults | after P2 (planned) |
| 6 Changes to the site | after P1 (planned) |
| 7 Rollback | now |

Read with: `manuals/site-layout-103.md` (the site, ids such as `MW-1`, `J-N`, `HOME-N`) and
`manuals/tracked-plan-3-tape-localization.md` (why). General operation, survey and fault codes:
`amr_ws/RUNBOOK.md`. **Planned** sections describe pages and buttons that do not exist yet. When
they are built, the procedures move into `amr_ws/RUNBOOK.md` and this file keeps only P0.

Roles: **E** = engineer (PIN pages, terminal), **O** = operator at the vehicle with the E-stop in reach.

## 1. Rules

- **Every autonomous move is AUTO + a physical Start on the panel.** Nothing here, not a call, not
  a teach run, not a script, starts the vehicle. Jogging is MANUAL + Manual Arm (DI08).
- **P0 does not stop `amr.service`.** It starts an extra localization launch beside the running
  LINE layer. That launch publishes only AMCL's pose and its `map→odom` transform, which LINE does
  not read. Restart the service only on the operator's go, and only to load new code.
- **Bench tools that need `can0`** (`read_mls …`) refuse while the service runs. They are not part
  of this runbook.
- **One test at a time on the vehicle.** Never start a simulation in the vehicle's domain (10).
- **MLS markers:** always on (2026-10-23, no profile switch). The Home Marker tile shows whether the
  sensor is configured for them (`manuals/mls-marker-plan.md`).

## 1A. Where the tests run now: the straight in front of MRU

Until the plant is free, sections 2 and 3 run on the ~10 m straight in front of MRU (plan 3
section 7). Differences from the text below:

- **Profile:** this stage uses `tape_loc.site_mission: test-mru-straight` and
  `tape_loc.shadow_circuit: C-STRAIGHT`. The profile now holds `site-103` / `C-MRU`, so switch it
  first (and back after).
- **T-HOME:** the east end of the free section, facing west. Mark it on the floor (the survey
  start too). **No RFID** (2026-10-18). The run is the job `mru-straight-markers` (Run tracked →
  Set job). It needs the marker stream up (Home tile).
- **Strips:** the layout is `manuals/tracked-plan-3-tape-localization.md` section 7.5 (drawing:
  `documentation/layout-reference/mru-straight-test-layout.html`). If the code-2 backstop is read
  on the way back, the home marker was missed: FAULT, jog back to T-HOME, Reset.
  No other code 1 or 2 strip anywhere on the straight.
- **Holds:**
  - `MARKERS_LOST`: the marker stream dropped while driving. Check where the AGV is, then Start.
  - FAULT "home marker missed": check the code-1 strip, jog back to T-HOME, Reset.
- **Stations on the straight:** T-HOME, T-ATT, MW-4, ME-4 (only MRU4 lies inside). The U-turn at
  the west tape end is CW.
- **One lap:**
  1. T-HOME westbound
  2. the tape-end pivot (U-turn tag, automatic)
  3. eastbound back to T-HOME
  4. O turns the AGV round by hand: selector **MANUAL**, Manual Arm, spin in place, **empty**
- **2.2 strips:** 2–3 code-3 strips on the straight, at least 3 m apart and 1 m from any stop.
- **2.3 survey:** only the free area. Drive it both ways, slowly; turn at the ends by hand.
- **2.5 / 2.6:** `tools/run_log.sh mru-straight-markers` per lap. A lap: Start at T-HOME, the
  AGV runs, pivots at the tape end, comes back and stops at T-HOME (DONE). Then turn it by hand.
- **3.2:** circuit `C-STRAIGHT`.
- **3.3 stations:** T-HOME (facing west), T-ATT (**at least 2 m west of T-HOME**), MW-4 facing
  west, ME-4 facing east.
- **Not testable here:** junction orders, fork resyncs, wrong branch, crossings. They wait for the plant.

## 2. P0 measurement session

Goal: measure how repeatably AMCL knows where the AGV is along the tape (plan 3 section 5,
metrics M1–M6). Nothing about motion changes: the AGV runs `line-a` exactly as today.

### 2.1 Before the session

| # | Who | Check |
|---|---|---|
| 1 | E | Built: `cd ~/agv_can/amr_ws && colcon build --symlink-install && source install/setup.bash`. `tape_loc.enabled` is **false** (P0 refuses to start otherwise). `pidstat` installed (`sudo apt install sysstat`) |
| 2 | E | `python3 tests/run_all.py` passes (repo root) |
| 3 | E | `amr.service` runs the current code: `tools/run_log.sh` warns in its pre-flight if it doesn't. Restart on O's go |
| 4 | E | MLS marker configuration in place (`read_mls set-markers --go` done, marker bench B2 or later; Home Marker tile not "sensor not set up"). If not, P0 uses the RFID fallback (plan 3 section 5); note it in the session log |
| 5 | O | `line-a` runs cleanly from Home today; the tape and tags are undamaged |
| 6 | O | An ordinary production day for the hall: racks and machines where they normally are. Note anything unusual |

Session log: a text file `~/.amr/runs/p0-<date>.md`. Record each step's time, the map revision,
every run stamp, and anything unusual (people in the aisle, trolleys moved, lost localization).

### 2.2 Lay the code-3 reference strips

> **Superseded 2026-10-23:** code 3 is now the guided run's U-turn **and** home marker (section
> 3.2A). Do not lay code-3 reference strips; remove any already down (the two on the MRU
> straight). P0 references will use taught positions instead.

Code 3 = a 60 mm strip **and** a 30 mm strip, as on the drawing
`documentation/layout-reference/mls-marker-codes-standard.html`:
- each strip 15 mm wide, 100 mm long, south pole up
- both on the same side of the tape

1. Lay 4–5 strips along the laid circuit, numbered **A1…A5** on a floor label:
   - one on the trunk straight
   - one before MRU1
   - one between MRU2 and MRU3
   - one between MRU4 and the tape end
   - one between Home and the trunk
2. Keep each strip:
   - **≥ 2 m from any speed-zone pair** (codes 2 and 1)
   - **≥ 1 m from any diverter, merge or crossing**
   - away from where the vehicle stops, so it is crossed at running speed
3. Write the distance from each strip to a fixed reference (pillar, tag) in the session log, and take a photo.
4. Check: one ordinary `line-a` run recorded with `run_log.sh`. `bag_report.py` must list a code-3 marker at every strip, in both directions. A strip that is missed or read as another code is re-laid before going on.

### 2.3 Survey the map

1. O: put a floor mark (taped arrow) where the AGV parks at `line-a` Home. It is both the survey
   start and AMCL's starting pose.
2. O: Home page → **Navigation → Trackless** (mode IDLE). Selector **MANUAL**, Manual Arm on.
3. E/O: Maps page → Map id `site103`, start mark description "line-a Home arrow" → **New map**.
   Then follow `amr_ws/RUNBOOK.md` section 2.A, and in particular:
   - drive the whole laid circuit **in both directions**, on or next to the tape, slowly
   - include the HOME area, and as much of row 2, the left vertical and the middle line as is
     reachable, so that P4 can use the same map
   - use preset moves on the long straights; turn slowly; pass the same places twice
4. Return to the mark → **Returned to start**. The closure must be a few cm and 1–2°; otherwise
   drive another loop.
5. **Save map revision**. Write `site103 rev N` in the session log.
6. Maps → **Edit areas**: mark places where trolleys and stock stand and move (the trolley and
   tread supermarkets, trolley parking) as dynamic areas.
7. O: Home page → **Navigation → Tracked** (mode LINE).

### 2.4 Start localization beside LINE

1. O: drive or jog the AGV onto the Home floor mark, facing the arrow, and keep it still.
2. E, in a second terminal on the vehicle:

   ```bash
   source ~/agv_can/amr_ws/env/vehicle.sh
   ros2 launch amr_bringup p0_localization.launch.py map_id:=site103 revision:=N params:=default initial:=start
   ```

3. E checks:
   - `ros2 topic echo --once /amcl_pose`: a pose near the start, with covariance xx and yy below 0.01.
   - In Foxglove, the live scan lies on the map's walls.

   If the scan does not align: Ctrl-C, re-park on the mark, launch again.
4. Leave it running for the whole set. Do not relaunch between laps unless localization is lost.

### 2.5 Set A: default AMCL parameters, 10 laps

For each lap:

1. E, third terminal: `tools/run_log.sh line-a MRU4`. Start it **before** the Start.
2. O: selector **AUTO** → **Start** on the panel. The AGV runs Home → MRU4 → U-turn → Home.
3. E: after the AGV stops at Home, press Ctrl-C **once** in the `run_log.sh` terminal. Write the
   run stamp in the session log.

While laps run, E watches Foxglove. If the AMCL pose leaves the tape by more than ~0.2 m, or jumps:
- write the lap and place in the log
- after the lap, at Home: Ctrl-C the launch, re-park on the mark, launch again

### 2.6 Set B: lean parameters, 10 laps

At Home: Ctrl-C the launch, re-park on the mark, launch with `params:=lean`, check as in 2.4,
then 10 laps as in 2.5.

### 2.7 Report

```bash
python3 tools/p0_report.py ~/.amr/runs/<stamp> ...     # the 10 stamps of set A
python3 tools/p0_report.py ~/.amr/runs/<stamp> ...     # the 10 stamps of set B
```

Copy both M1–M6 tables into plan 3's **P0 results**, with the date, the map revision, the run stamps
and the session log's notes. Apply plan 3's decision rule (section 5).

### 2.8 Close

1. E: Ctrl-C the localization launch.
2. O: keep the code-3 strips if the decision keeps anchors; otherwise remove them.
3. The map revision is kept. P1 teaches on it.

## 3. Teach the tape graph (P1)

Teach when: a new map revision, newly laid tape, or a moved station (section 6). Teaching is done
empty, with no trolleys. All of it is on the **Teach** page (engineer nav, PIN). The page records
and publishes only; the AGV moves by the panel's Start, or by jogging under MANUAL.

### 3.0 Once: switch tape localization on

1. E: `profiles/agv-01.json` → `"tape_loc": {"enabled": true, ...}`.
2. E: `cd ~/agv_can/amr_ws && colcon build --symlink-install` (new messages and services), then
   restart `amr.service` on O's go.
3. Teach page → Map `site103`, rev `N` → **Select map**. This writes `~/.amr/line_graph.json`.
4. Load it into LINE: Home → Navigation → **Trackless** → **Tracked** (or a service restart on O's
   go). Teach → **Status** must say "teaching on site103 revN: no graph active". The LINE layer now
   runs map_server, AMCL and the localization monitor beside the follower.

### 3.1 Localise

1. O: AGV on the survey start mark (the `line-a` Home arrow).
2. E: give AMCL its initial pose:
   - first time, with no graph yet: Foxglove "2D Pose Estimate" on the mark, or
     `ros2 topic pub --once /initialpose …`
   - once HOME-N is taught: **At home** at HOME-N
3. E: **Scans align** once the live scan lies on the walls. The Readiness tile must show READY.

### 3.2 Record the circuit passes

A pass is one whole circuit: out of the HOME bay, through every junction and the U-turn, back
into the bay, ending where it started (within 0.5 m).

1. E: Circuit `C-MRU` → **Record pass**. The Graph tile shows the pass being recorded.
2. O: selector **AUTO** → **Start**: a **guided run** (section 3.2A). `line-a` does not drive
   this layout.
3. Back in the bay, standing: E **Stop pass**. The message gives the length, poses and forks seen.
   - A pass whose MLS fork episodes and U-turn do not match the circuit's junctions is refused,
     with both lists: an MLS that missed a fork, or a route that differs from the mission.
   - People or trolleys in the way during a pass: **Discard** and record it again.
4. Repeat until there are **3 good passes** (**Passes** lists them).
5. E: **Build**. Each leg is listed with its pass count and spread. A spread above 5 cm means
   recording that circuit again.

### 3.2A The guided run (2026-10-23)

Mission `c-mru-guided`. The engineer walks beside the AGV and gives each branch order by hand.
Drawing: `documentation/layout-reference/c-mru-route.html`.

| | |
|---|---|
| Speed | 0.4 m/s outside HIGH (0.3 until 2026-10-24). **Speed** toggle on the Guide page (2026-10-24), **Normal** at every mission load: Normal ignores the corner code-1/2 strips; High lets them act as in `line-a` - HIGH (0.85 m/s) only after an outer 2 then inner 1, NORMAL again at the exit 1 / 2, back to 0.4 m/s after it. The toggle never raises the speed by itself; Normal mid-straight drops HIGH at once |
| Branch orders | **Guide** page (engineer PIN), on a phone or a laptop: ◀ Left / ▲ Straight / Right ▶, or the arrow keys |
| U-turn | MLS **code 3** about 1 m before the MRU tape end: creep at 0.1 m/s, stop where the tape ends, pivot CW |
| Home | MLS **code 3** in the north bay, **0.5 m before HOME-N** on the way back in: a measured stop there, run DONE |
| Telling them apart | a code 3 counts only after 40 m of wheel travel from either end (`home_arm_m`): out, since Start (the departure crosses the home strip and the HOME complex junctions); back, since the pivot (and the U-turn strip's own re-pass is skipped). Earlier reads are a WARN on the Events list |
| Junctions | the MLS decodes a merging, diverging or crossing tape as a marker (code 2 at J-BMERGE, code 3 at X1 and into J-ML, 2026-10-23). A U-turn/home read acts only after 0.3 m with one tape under the sensor, before and after it; otherwise WARN "ignored: a junction". Strips stay ≥ 1 m from any junction |

1. Lay the two code-3 strips. The home strip goes on the return path into the north bay, 0.5 m
   before where the AGV should stop. The AGV starts at HOME-N, past the strip. Both strips
   must be more than 40 m of tape from HOME-N (the U-turn strip from the start, home from the
   pivot), and ≥ 1 m from any junction.
   Corners with no radius (kinks; the HOME complex tape is grooved): the follower holds a
   deflection up to ~40 deg. Sharper, the tape leaves the sensor at its edge, and the AGV
   stops, pivots toward it until the tape is within ±`kink_stop_mm` (75 mm, not centred: the
   sensor sits close to the axle, so centring over-rotates) and goes on (Events: "kink: the
   tape left the sensor at ... mm" then "kink: pivoted ... deg, tape at ... mm - resuming").
   A ~60 deg corner may take a second short pivot. A tape that leaves
   near the centre is still the tape end. No tape within `kink_max_deg` (75 deg): FAULT,
   align on the tape, Reset, Start. A protective stop mid-pivot resumes the search. The
   pivot adds nothing to the along-tape distance and no junction to a teach pass.
2. Run page → mission `c-mru-guided`. Open **Guide** on the phone.
3. **An order is one shot: the next fork or MERGE the MLS sees uses it, then it is Straight
   again.** Set it after the previous junction:

   | Where | Order |
   |---|---|
   | leaving the bay: J-BMERGE (merge), R717 | Straight (nothing armed) |
   | after R717, before J-N | **Right** |
   | X1, J-ML (merge onto the trunk), MRU line | Straight |
   | back down the trunk, before J-ML | **Left** (R1380; R2434 is the wrong way) |
   | J-STEM (merge) | Straight |
   | after J-STEM, before J-SPLIT | **Left** (north bay) |

4. Any order still armed at the pivot is cleared. Reset clears it too.
5. Nothing on the Guide page moves the vehicle: AUTO + the physical Start, as always. Keep the
   E-stop in reach.
6. The U-turn strip sits close to the MRU tape end: a read there turns even inside the 0.3 m
   junction guard. If the strip is missed, press **U-turn at tape end** on the Guide page before
   the end (on the way out only): the next tape end is the U-turn instead of the run ending
   "track lost". One shot, **Cancel** undoes it. Too late once the run has ended: MANUAL and
   the pendant.
7. **Marks** (2026-10-24): **Mark here** on the Guide page (or the M key, or the Teach page)
   records where the AGV is at that moment, driving or standing: the last AMCL pose projected
   onto the leg it faces, moved on by the wheel travel since (about +/-10 cm at 0.3-0.4 m/s).
   They are saved per map revision as M1, M2, ... (`~/.amr/teach/<map>-rev<R>/marks.json`)
   with an optional label; their role (station, zone edge, ...) is given later. Needs built
   legs (Build, or an active graph) and READY. Teach page: **Marks** lists them, **Delete
   mark** with an M-id in the field. Build re-projects them onto re-averaged legs.
8. **Overlay:** the Run page map draws the tape graph (or, before one is published, the newest
   pass, dashed), the junction anchors, the stations and the marks - on the map revision they
   were taught on only.

### 3.3 Teach the stations

For each station: HOME-N, ATT, MW-1…MW-4, ME-4…ME-1 (and R2-1…R2-8 once row 2 is laid):

1. O: selector **MANUAL**, Manual Arm on. Jog the AGV to exactly where the operator wants it to
   stop, facing its travel direction:
   - MW = westbound
   - ME = eastbound
   - spin in place to turn it, empty only
2. If AMCL has not updated since the last move (it updates only on motion), nudge the AGV a few
   centimetres and stop again.
3. Hold still for **3 s**. E: Station → id → **Teach here**.
4. The message gives the leg, `s` and the distance from the taught tape. It refuses when:
   - the AGV is more than 10 cm from the tape
   - it faces the wrong way for the station's leg
   - localization is not READY, or there were fewer than 5 poses in the 3 s
5. **Build** again: it says "every circuit compiles", or lists what is missing. Today C-BTU stays
   incomplete: row 2 is not laid.

### 3.3A Stations and points from marks (tracked plan 4, E0)

The faster way to teach (2026-10-24): mark while driving (3.2A item 7), give each mark its role
afterwards.

1. E: Teach page → Mark field: the mark's id (`M6`) → Role: the station or point → **Set role**.
   - Roles: every station (HOME-N, ATT, MW-x, ME-x), every mid-line U-turn point
     (`uturn_points` in `missions/site-103.json`).
   - The message gives the leg and `s`. It refuses a role whose leg the mark is not on, or that
     faces the wrong way (an MW role on an eastbound mark).
   - A role moved to another mark leaves the first one. Role `-` removes it.
2. **Roles** lists what is taught, from which mark, and what is not.
3. **Build** puts them in the graph, then **Publish**, **Make active** (3.4).
4. INBOUND stops (ME-x) either get marks on their own eastbound lap (the outbound lap's marks
   face west), or are placed by a floor offset from the outbound mark (2026-10-25):
   - measure on the floor from the release spot to the attach-full spot, along the tape;
   - Mark field `M8 M12` (reference, new id) → Offset `1.20` → **Mark inbound at offset**;
   - + is the way the inbound AGV drives (east, toward J-ML), − the other way;
   - then give M12 its role (ME-1) as in step 1.
   - A U-turn point the same way along the outbound tape: Mark field `M8 M16` → Offset `1.4` →
     **Along at offset** (+ = onward, toward the line's end), then role UT-MRU1.
5. A U-turn point must lie after its machine's release stop. Its take-back stop must lie after
   the point's place on the return leg. Otherwise the trip is refused at Start, with the station
   named.

### 3.3B High-speed areas (2026-10-25)

High speed is where the tape runs inside an area drawn on the map, not between marks.

1. E: Teach page → **High-speed areas →** (`/tape-areas`). The teaching map shows with the tape
   graph and the marks.
2. **Draw new** → click each corner → Id → **Save area**. **Delete** in the list removes one.
3. A trip is HIGH only where its route lies inside an area for at least 1 m, only with the locator
   healthy. It slows back to the cruise before every stop, junction and area end.
4. Areas count from the next trip on, with no Build. The shadow lap logs "high-speed area: HIGH
   from …" and "NORMAL by …" where the circuit enters and leaves each one.

### 3.4 Publish and make active

1. E: **Publish** creates graph revision `g<N>` under the map. It never changes afterwards.
2. g `N` → **Make active**.
3. Load it: Trackless → Tracked, or a service restart on O's go. Status names the graph, and the
   Locator tile shows IDLE.

### 3.5 Shadow verification

1. O: AGV at HOME-N. E: **At home** → **Scans align** → READY. The Locator tile goes WAITING →
   HEALTHY.
2. Ordinary `line-a` runs, recorded with `tools/run_log.sh`. The locator only logs. At every
   station, junction order and U-turn approach, the event log (`LINE_LOC`) says "would stop / would
   order … : ok", or "would HOLD" with the reason. LOST, re-acquired and unexpected forks are logged
   too.
3. Acceptance: plan 3 section 4, P1. Any "would HOLD" or LOST gets looked at before P2.
4. Plan 4 E2: the log also names each taught U-turn point ("U-turn point of MRU1 UT-MRU1 …") and
   high-speed area entry and exit ("high-speed area: HIGH from …"). Five Guide-page laps: every "would order" matches the
   order given by hand, every "would stop" lies within ±10 cm of its floor mark.

## 4. Daily operation (built 2026-10-24, off until `tape_loc.live: true`)

The position engine (tracked plan 4) drives trips once the profile says `tape_loc.live: true`.
That is after E2 (3.5 item 4). The site mission is then the line job at start-up (Run tracked lists
it too), and the **Calls** tab runs it. The new LineState fields need `colcon build` of
`amr_interfaces` (`amr_ws/README.md`). Without the build the Calls page says so, and trips still run.

### 4.1 After power-on

1. The service enters LINE. The Localisation tile shows UNLOCALIZED.
2. With the AGV parked at HOME-N: Calls page → **At home** → confirm that the scans align → READY.
3. If the AGV is **not** at HOME-N: jog it there under MANUAL first.

### 4.2 Calls and trips

1. **Calls.** A machine operator taps their machine on the Calls page (touch panel or laptop). The page lists pending calls per group (MRU, BTU).
2. **A trip forms** at two calls of one group: "Trip MRU: MRU2, MRU4: press Start at the bay". A call for the other group waits.
3. **Start at the bay.** O: selector **AUTO** → **Start** at HOME-N. Horn, then the AGV drives **empty** through the U-turn and stops at ATT.
4. **Attach.** O attaches the trolleys → **Start**.
5. **At each machine:**
   - **BTU:** swap the trolley → **Start**. Two calls at one shared point are one stop.
   - **MRU, outbound (westbound):** release the trolley → **Start**. After the last release:
     - the AGV stops at that machine's U-turn point and pivots there, empty;
     - with no U-turn point taught for that machine, it pivots at the tape end.
   - **MRU, inbound (eastbound):** it stops at the same machines in reverse order. Take the trolley back → **Start**.
6. **Back at HOME-N:** release the trolleys → Calls page **Trolleys off**. The trip is done, and the next trip can start.

### 4.3 What the screen shows

- **Localisation tile:** READY / CHECKING / LOST.
- **Locator line** in the rail: edge, `s`, σ, and HEALTHY / DEGRADED / LOST.
- **Run tile and message:** the next stop or junction, and why the AGV is held.

## 5. Holds and faults (built 2026-10-24 with the position engine)

Alarm codes: `POSITION_UNSURE` (hold `position`) and `PAYLOAD_UNCONFIRMED` (hold `payload`). A
FAULT during a trip aborts it: so do a tape lost, a wrong branch, Reset and Clear. The event log
says what was served. Bring the AGV to HOME-N under MANUAL, **At home**, Reset. The machines then
call again.

| Code / cause | Operator sees | Operator does |
|---|---|---|
| HOLD `position` before a station or junction | "position uncertain before MW-2" | Check that nothing blocks the scanner's view (people, trolleys parked in the aisle). When the Locator line shows HEALTHY, press **Start**. If it does not recover within a minute: MANUAL, jog to HOME-N, **At home**, and call E |
| HOLD `position` mid-route, localization LOST | "localization LOST (…)" | As above: it stays held, and every **Start** re-checks (`tape_loc.lost_fault_s` is not acted on yet). Not recovering: MANUAL, jog to HOME-N, **At home**, Reset. Handle the trolleys by hand |
| HOLD `payload` at the U-turn (point or tape end) | "release not recorded for MRU1: a trolley may still be attached" | Check the trolley. If it is attached, release it here → Calls page **Released** → **Start**. The AGV never pivots with a trolley; Start alone does not pivot |
| Trip Start refused `payload` at HOME-N | "trolleys from the last trip not confirmed off" | Release them → **Trolleys off** → **Start** |
| FAULT `wrong_branch` | "took the wrong tape after J-…" | The AGV is stopped. MANUAL: jog back to HOME-N, **At home**, Reset. Call E: the junction or its taught geometry needs checking |
| Unexpected fork (logged, `LINE_LOC`) | "fork with no taught junction near S …" | Logged only, no hold yet. If it repeats, call E (tape damage or a changed layout) |
| FAULT: an order not used | "order right for J-N not used: no fork seen within 1 m of where J-N is taught" | MANUAL: check which tape the AGV is on, jog to HOME-N, **At home**, Reset. Call E |
| Site mission refused at layer start | "graph g3 is for map rev 4, active map is rev 5" | E: Teach page → make the matching graph active, or re-teach (section 6) |
| `LAYER_EXITED` | "the line software stopped" | **Recover** on the Status page (`amr_ws/RUNBOOK.md` section 4), jog to HOME-N, **At home** |

## 6. Changes to the site (planned, P1)

| What changed | Redo | Result |
|---|---|---|
| Tape re-laid on one section | record that circuit's edges again (3.2), then re-teach the stations on those edges (3.3) | new graph revision |
| A machine's stop position moved | re-teach that station (3.3) | new graph revision |
| Racks or stock moved a lot; frequent `position` holds on one section | first mark dynamic areas (`amr_ws/RUNBOOK.md` 2.A2); if that is not enough, a new survey | a new survey = new map revision → full re-teach (3.1–3.4) |
| New map revision for any reason | full re-teach | the old graph is refused for the new map |

A graph or map revision is never edited in place. The previous one stays and can be made active again.

## 7. Rollback

1. E: set `tape_loc.enabled: false` in `profiles/agv-01.json`.
2. Restart `amr.service` on O's go.

LINE then runs without AMCL, as before this plan: `line-a`, RFID stops. Taught graphs
(`~/amr_maps/<map>/tapegraph/g<N>`), passes (`~/.amr/teach/`) and the active pointer
(`~/.amr/line_graph.json`) are kept for when it goes back to `true`. In P1 nothing the locator says
reaches motion, so switching it off changes nothing about how the AGV drives.
