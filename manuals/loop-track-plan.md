# Loop track plan: one closed tape loop, HOME to HOME on each Start

Status 2026-11-25: **built** on branch `gvievo-ce` (uncommitted), dev-box tests only
(`amr_ws/src/amr_line/test/test_loop_track.py`, 21 tests; the line, mission, web, station and
config tests fail exactly as at HEAD). Not run on the vehicle. Operating steps:
`manuals/tape-localization-runbook.md` section 6A. The profile still names `site-103`: switch
it (6A step 0) when the unit is at the loop site.

As built, differences from the design below:

- HOME taught at the seam resolves to the START of the loop leg (s ≈ 0), so the arrival at HOME
  falls mid-route (the route lays the leg twice) and an overrun is tracked, not clamped.
- The job needs no loop branches: a loop site gets `trip.LoopQueue` (always a lap ready, no
  calls) and `trip.NoPayload` (never holds a Start). `job.py` changes only in `_set_site`,
  the run message, and `end_lap()`.
- `guided.end_stop_m` is optional on any guided mission (default 0.5 m).
- Not built: the `SEAM_M` refusal of a station near the seam (3.3). A loop site has no station
  but HOME, so there is nothing to refuse yet; add it with stops along the loop.
- Run page: on a loop site the Calls card says "a loop: each Start at HOME drives one lap" and
  hides the trolley confirmations (`/api/line/site` carries `loop`).
- Tests: `test_loop_track.py` (21; the runtime one needs the vehicle's file system, it passes
  on the dev box only with a scratch fsync shim) and `test_server.py`
  `test_guided_end_lap_needs_the_engineer`.

## 1. What the owner wants

- The tape is one closed loop (for example a rectangle): no junctions, no U-turn.
- No MLS marker strips: not for HOME, not for speed.
- The AGV stands at HOME. **AUTO + Start**: it drives one lap and stops at HOME.
  **Start** again: the next lap. Nothing else: no calls, no trolleys, no ATT, no stations
  on the way.
- High-speed areas and dynamic areas, as on site 103.

Commissioning once this is built:

1. Floor arrow at HOME. Survey (Mapping → Survey, preset moves, both directions), close at the
   arrow, **Save map revision**.
2. Dynamic areas with `map_edit`. This writes rev N+1: teach on that one.
3. Teach → **Select map** → Restart tape layer → initial pose on the arrow (first time by
   hand) → **Scans align** → READY.
4. **Record pass** → AUTO + Start on `c-loop-guided` → the AGV follows the loop → past the
   arrow, **End lap** (Guide page) → **Stop pass**. Three passes, **Build**.
5. Back on the arrow: Station HOME → **Teach here**.
6. High-speed areas on `/tape-areas`.
7. **Publish** → **Make active** → Restart tape layer.
8. Shadow laps, then `tape_loc.live: true`. From then on: AUTO + Start = one lap.

The position along the loop comes from AMCL on the map plus the wheels. The HOME stop is the
taught HOME, so no marker is needed.

## 2. Why today's code does not do it (read in the code)

| # | Where | What |
|---|---|---|
| B1 | `agv_core/mission.py:683` `_site_legs` | A circuit with no laid junction or U-turn is refused: "nothing to split the tape at" |
| B2 | `agv_core/mission.py:700-800` `_parse_site` | A site mission requires ATT (first stop after HOME), at least one group, machines, `trip_calls` |
| B3 | `amr_line/job.py:536-566` `_trip_check`, `_trip_take` | A live Start needs a formed trip (calls from Run → Calls) and the trolleys confirmed off |
| B4 | `amr_line/tape_teach.py:223-261` `split_pass` | Cuts a pass at node events. With none, `b[0]`, `b[-1]`, `events[0]` do not exist |
| B5 | `amr_line/tape_teach.mean_leg` | Passes are matched by length fraction within `WINDOW_M` (0.5 m). Loop passes that start at different floor points would not average, while Build still shows a good spread |
| B6 | `amr_line/tape_graph.py:162` `Leg` | `end_kind` must be `fork`, `uturn` or `none` |
| B7 | `amr_line/tape_graph.py:358` `_node` | The seam between the lap and the next is made a `junction` node |
| B8 | `amr_line/tape_run.py:442-500` | A guided run ends at HOME only on a code-3 strip after a pivot. With no `marker_run` it follows the loop forever |

Reused unchanged:

- **Locator** (`tape_locator.py`): AMCL corrects S all the time, projected within a window
  around the predicted S. Junctions are only extra resyncs.
- **`compile_trip`** (`trip_route.py:224`): one leg is laid `[leg, leg]`. The start HOME lands
  on the first copy and the arrival HOME on the last, which is exactly one lap.
- **Shadow** (`tape_runtime._shadow_tick`): at `S_end` it subtracts one lap and starts the next.
- **High-speed areas**: drawn on the map, cut into ranges along the trip.
- **At home**, auto-confirm, the 2 s warning horn on Start, protective-field holds: unchanged.

## 3. Design

### 3.1 A loop site mission (`agv_core/mission.py`)

A new small schema `loop-1`, parsed into the same internal shape as a site mission, so the
locator, teach and trip code see what they already know:

```json
{
  "schema": "loop-1",
  "mission_name": "loop-site",
  "home": "HOME",
  "stop_distance_m": 0.5,
  "cruise_mps": 0.5
}
```

Parsed: `HOME`, `STOP_DISTANCE_M`, `CRUISE_MPS` (both checked as in `_parse_site`),
`LOOP: True`, `ATTACH: None`, `GROUPS: {}`, `MACHINES: {}`, `JUNCTIONS: {}`, `UTURNS: {}`,
`UTURN_POINTS: {}`, `POINTS: {}`, `TRIP_CALLS: 0`, one circuit `C-LOOP` with
`items` `[HOME, HOME]`, one leg `HOME>loop>HOME`, `home_depart` `[HOME]`,
`home_arrive` `[HOME]`, `STATIONS: {HOME: leg}`. `is_site()` accepts `loop-1`.
`_parse_site` and `_site_legs` are not touched.

### 3.2 Starting a lap (`amr_line/job.py`, `trip.py`)

- `trip.LoopTrip(mission)`: the same surface `compile_trip` and the job use (`circuit`,
  `plan` = `[{"id": HOME, "role": "home", "work": []}]`, `uturn()` → None, `stops()`,
  `describe()` → "lap"), no machines.
- `_trip_check` with `LOOP`: only `_site_at_home` (at HOME, sigma under `sigma_junction_m`)
  and `_home_moved`. No calls, no payload.
- `_trip_take` with `LOOP`: `LoopTrip`, compiled as today. Nothing to put back on a refusal.
- Payload: never created for a loop site. Guard `payload.trip_ended()` (`job.py:1269`) and
  the other `self.payload` / `self.calls` uses (about 36 lines in `job.py`) for `None`.
- `station.enabled` with a loop site is refused at layer start (no orders on a loop).
- Arrival at HOME: the ordinary home stop, run DONE, horn off. The next Start is the next lap.

### 3.3 Teaching (`amr_line/tape_teach.py`, `tape_graph.py`)

`split_pass` for a loop circuit:

1. **Close.** Project the pass's first point onto the second half of the pass
   (`line.project(x, y, s_lo=length/2)`) and cut there: one closed lap. Refuse if the pass
   ended more than `HOME_GAP_M` (0.5 m) short of its start.
2. **Rotate to one reference point R.** R is the taught HOME pose once there is one, else
   the first saved pass's start. Find where the lap passes R (lateral ≤ 0.15 m, facing the
   same way) and start the lap there. Every pass then starts and ends at one floor point, so
   `mean_leg` averages like with like (B5). Refuse a pass that does not pass R.
3. Refuse a pass shorter than `LOOP_MIN_M` (5 m).

Plus:

- `end_kind` `"loop"`, accepted by `Leg` and kept through publish/load (B6).
- MLS fork episodes on a loop pass (corner pivots) are noted and ignored.
- HOME taught within `SEAM_M` (1.0 m) of the seam resolves to s ≈ 0 (B7 side: the seam is
  at HOME by construction, step 2).
- `_node` after a `loop` leg: kind `"seam"`, `fork: False`, no order (B7). Skip `seam` in
  `decision_points`, the locator's `_ordered` / `_alts`, `site_run`, the shadow. Audit every
  `n["kind"]` test for an `else` that would treat it as a junction.

### 3.4 The teach lap: End lap (`tape_run.py`, `line_follow_node.py`, web)

- `TapeRun.end_here()`: in a guided mission, while driving, begin the ordinary measured stop
  (`_begin_stop` with role home, as at `tape_run.py:520`), run DONE. Its distance is
  `guided.end_stop_m` (default 0.5). Refused when not guided, not driving, or already stopping.
  It never starts or resumes anything.
- Service `/amr/line/end/here` next to `/amr/line/uturn/force`. Guide page button **End lap**
  (key E).
- `missions/c-loop-guided.json`: `{"mission_name": "c-loop-guided", "branch_default":
  "straight", "branch_latch": [], "high_zone": null, "tags": [], "guided": {"cruise_mps": 0.4,
  "end_stop_m": 0.5}}`.
- Overrunning the arrow is harmless (3.3 cut and rotate). The next pass may start where the
  last one stopped.
- Only for teaching. Live laps stop at the taught HOME, with no button.

### 3.5 Profile, web, docs

- `profiles/agv-01.json`: `tape_loc.site_mission: "loop-site"`, `shadow_circuit: "C-LOOP"`,
  `live` false until step 8.
- Run page: the Calls tab and the "trolleys off" control are hidden on a loop site. The run
  message says "lap: press Start at HOME".
- `manuals/tape-localization-runbook.md`: a "Loop site" section with section 1's steps.

## 4. Work packages

| WP | Files | Content |
|---|---|---|
| L1 | `agv_core/mission.py`, mission tests | `loop-1` schema |
| L2 | `amr_line/tape_teach.py`, `tape_graph.py` | Close, rotate to R, `LOOP_MIN_M`, `end_kind` `loop`, seam node |
| L3 | `trip_route.py`, `tape_locator.py`, `site_run.py`, `tape_runtime.py` | `seam` audit |
| L4 | `amr_line/trip.py`, `job.py` | `LoopTrip`, Start at HOME = a lap, payload/calls guards |
| L5 | `tape_run.py`, `line_follow_node.py`, `amr_web` | End lap |
| L6 | `missions/`, profile, Run page, runbook | Data, UI hiding, docs |

Order: L1 → L2 → L3 → L4. L5 can be built alongside them. L6 comes last.

## 5. Tests (dev box, `python3.11`, fcntl shim)

- Loader: `loop-1` parses to one circuit, one leg; `site-103.json` parses exactly as today.
- Synthetic rectangle (20 × 8 m, AMCL noise 2 cm):
  - one pass closes; overrun 1.5 m is cut; ended 0.8 m short is refused; a 3 m pass is refused;
  - three passes starting 1.5 m apart rotate to R, one leg, spread < 5 cm;
  - a pass that never passes R is refused;
  - the loop leg survives publish and load.
- `compile_trip(LoopTrip)`: stops HOME → HOME one lap apart, one `seam` node, no orders,
  no U-turn; high-speed areas cut into the lap.
- Job: Start at HOME with no calls starts a lap; Start away from HOME is refused; arrival
  at HOME is DONE; a second Start starts lap 2; no payload or calls touched.
- Locator and shadow over five simulated laps: S continuous across the seam, no resync there,
  sigma does not creep from lap to lap.
- `end_here()`: measured stop, DONE; refused unguided, held, or mid-stop.
- `python3 tests/run_all.py` passes; site-103 golden runs unchanged.

## 6. On the vehicle (cannot be run on the dev box)

1. `colcon build --symlink-install`, restart `amr.service` on the operator's go.
2. Survey; save; dynamic areas; Select map.
3. One guided lap with Record pass and End lap: Stop pass says one leg, closed.
4. Three passes, Build: spread ≤ 5 cm. Teach HOME on the arrow. Publish, Make active.
5. Five shadow laps: "would stop" at HOME within ±10 cm of the arrow each lap, Locator stays
   HEALTHY across the seam.
6. `tape_loc.live: true`: AUTO + Start, one lap, stops at HOME; Start again, second lap.
   Measure the stop against the arrow each lap.

## 7. Open checks

- `job.py` holds about 36 uses of calls, payload, ATT and groups. Each one needs a loop-site
  guard (L4). This will be the longest part of the change.
- `site_run.py` and `tape_locator.Shadow`: the `seam` audit (L3).
- Stop accuracy at HOME rests on AMCL alone (no junction or marker resync). On site 103 the
  station limit is sigma 2.5 cm. A featureless stretch just before HOME would show as a
  DEGRADED locator and a looser stop. Step 6.5 measures it.

## 8. Risks

- **No regression:** `loop-1` is a separate schema. Site missions, `_parse_site` and
  `_site_legs` are untouched. The teach and route changes trigger only on a `loop` leg.
- **Rectangle corners:** driven by the existing rolling-corner/kink logic, unchanged. Their
  MLS fork-like episodes are ignored on a loop pass.
- **Later stations on the loop** (a stop with "press Start to go on"): not in this plan. The
  `loop-1` schema can take a `stops` list later without changing the rest.
