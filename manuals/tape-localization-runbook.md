# Tape localization runbook: AGV-01, site 103

Status 2026-10-17. What each section needs before it can be used:

| Section | Usable |
|---|---|
| 1 Rules | now |
| 2 P0 measurement | once tooling T1–T3 is built (plan 3 section 5) |
| 3 Teach | after P1 (planned) |
| 4 Daily operation | after P2 + P3 (planned) |
| 5 Holds and faults | after P2 (planned) |
| 6 Changes to the site | after P1 (planned) |
| 7 Rollback | after P1 (planned) |

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
- **MLS markers:** `mls.markers_enabled` is the bench switch. It is `true` only during a bench
  session or after the marker bench passed (`manuals/mls-marker-plan.md`).

## 2. P0 measurement session

Goal: measure how repeatably AMCL knows where the AGV is along the tape (plan 3 section 5,
metrics M1–M6). Nothing about motion changes: the AGV runs `line-a` exactly as today.

### 2.1 Before the session

| # | Who | Check |
|---|---|---|
| 1 | E | T1–T3 merged and built: `cd ~/agv_can/amr_ws && colcon build --symlink-install && source install/setup.bash` (a new launch file and tool need the build) |
| 2 | E | `python3 tests/run_all.py` passes (repo root) |
| 3 | E | `amr.service` runs the current code: `tools/run_log.sh` warns in its pre-flight if it doesn't. Restart on O's go |
| 4 | E | MLS marker configuration in place (`read_mls set-markers --go` done, marker bench B2 or later) and `mls.markers_enabled: true`. If not, P0 uses the RFID fallback (plan 3 section 5); note it in the session log |
| 5 | O | `line-a` runs cleanly from Home today; the tape and tags are undamaged |
| 6 | O | An ordinary production day for the hall: racks and machines where they normally are. Note anything unusual |

Session log: a text file `~/.amr/runs/p0-<date>.md`. Record each step's time, the map revision,
every run stamp, and anything unusual (people in the aisle, trolleys moved, lost localization).

### 2.2 Lay the code-3 reference strips

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
3. E: `mls.markers_enabled` stays `true` only if the marker bench has passed. Otherwise set it back
   to `false` and restart the service on O's go.
4. The map revision is kept. P1 teaches on it.

## 3. Teach the tape graph (planned, P1)

Teach when: a new map revision, newly laid tape, or a moved station (section 6). Teaching is done
empty, with no trolleys.

### 3.1 Start a graph

1. E: Teach page (engineer PIN) → **New graph** → choose the map revision.
2. O: AGV at HOME-N → Calls page **At home** → confirm the scans align. The Localisation tile must
   show READY.

### 3.2 Record each circuit's edges

1. E: Teach page → **Record circuit** → `C-MRU` (later `C-BTU`).
2. O: selector **AUTO** → **Start**. The AGV follows the circuit at NORMAL, empty, and back to HOME-N.
   - The page shows the next expected junction, and each fork the MLS sees as it happens.
   - Until P2, the MRU U-turn is still triggered by its RFID tag, as in `line-a` today.
3. Repeat until the circuit has **3 passes**.
4. The page shows the spread between passes for each edge. Above 5 cm, record that edge again
   (people or a trolley in the way during one pass is the usual cause).

### 3.3 Teach the stations

For each station: HOME-N, ATT, MW-1…MW-4, ME-4…ME-1 (and R2-1…R2-8 once row 2 is laid):

1. O: selector **MANUAL**, Manual Arm on. Jog the AGV to exactly where the operator wants it to
   stop, facing its travel direction:
   - MW = westbound
   - ME = eastbound
   - spin in place to turn it, empty only
2. E: Teach page → choose the station id → **Teach here**. Hold still for 3 s.
3. The page shows the edge, `s` and the lateral residual. It refuses when:
   - the residual is over 5 cm ("not on the tape here")
   - the heading is wrong for the station
   - localization is not READY

### 3.4 Check and publish

1. E: Teach page → **Check against mission** (`site-103`). Every junction and station id must be
   present, and every order valid.
2. **Publish** creates graph revision `g<N>`, which never changes afterwards.
3. **Make active.**
4. Load it: Home → Navigation → Trackless → Tracked, or a service restart on O's go.

### 3.5 Shadow verification

The locator runs during ordinary `line-a` runs and only logs. Record runs with `run_log.sh`;
`bag_report.py` lists, at each station, the locator's `s` against the taught `s`. Acceptance:
plan 3 section 4, P1.

## 4. Daily operation (planned, P2–P3)

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
   - **MRU, westbound:** release the trolley → **Start**. After the last release the AGV pivots at the tape end, empty.
   - **MRU, eastbound:** it stops at the same machines in reverse order. Take the trolley back → **Start**.
6. **Back at HOME-N:** release the trolleys → Calls page **Trolleys off**. The trip is done, and the next trip can start.

### 4.3 What the screen shows

- **Localisation tile:** READY / CHECKING / LOST.
- **Locator line** in the rail: edge, `s`, σ, and HEALTHY / DEGRADED / LOST.
- **Run tile and message:** the next stop or junction, and why the AGV is held.

## 5. Holds and faults (planned, P2)

| Code / cause | Operator sees | Operator does |
|---|---|---|
| HOLD `position` before a station or junction | "position uncertain before MW-2" | Check that nothing blocks the scanner's view (people, trolleys parked in the aisle). When the Locator line shows HEALTHY, press **Start**. If it does not recover within a minute: MANUAL, jog to HOME-N, **At home**, and call E |
| HOLD `position` mid-route, localization LOST | "localization lost" | As above. After 30 s without READY it becomes a FAULT: MANUAL, jog to HOME-N, **At home**. Handle the trolleys by hand |
| HOLD `payload` before the MRU tape end | "MRU release not recorded: a trolley may still be attached" | Check the trolley. If it is attached, release it here → Calls page **Trolley released** → **Start**. The AGV never pivots with a trolley |
| Trip Start refused `payload` at HOME-N | "trolleys from the last trip not confirmed off" | Release them → **Trolleys off** → **Start** |
| FAULT `wrong_branch` | "took the wrong tape after J-…" | The AGV is stopped. MANUAL: jog back to HOME-N, **At home**, Reset. Call E: the junction or its taught geometry needs checking |
| HOLD `position`: unexpected fork | "a junction where none is expected" | Check where the AGV is and the tape under it. If all is in order, **Start**. If it repeats, call E (tape damage or a changed layout) |
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

## 7. Rollback (planned, P1)

1. E: set `line.localization: false` in `profiles/agv-01.json`.
2. Restart `amr.service` on O's go.

LINE then runs as before this plan: `line-a`, RFID stops. Taught graphs and maps are kept for
when the flag goes back to `true`.
