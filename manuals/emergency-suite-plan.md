# Home screen and emergency suite plan: gvievo-01 (agv-01)

Branch `gvievo-main` · 2026-11-12 · **Part A built 2026-11-12** (uncommitted; service restart and the A4 operator check owed). Part B not implemented.

- **Part A, Home screen: do now.** One full-width status tile, with colour by state and a localize
  instruction; one big Manual/Auto tile; the job, RFID and marker tiles removed. Web only, built on
  signals that exist today. **No E-stop wiring, no interface change, no colcon build.**
- **Part B, Emergency suite: POSTPONED** (owner, 2026-11-12) until Flexi Soft Q3 is wired to the DIO.
  It is a port of `origin/kyb-trackless` (MCQ4-4), commits 243433c, 481ffda and c36c8d2 (2026-10-30),
  with that branch's `manuals/emergency-suite-plan.md` as the design source. When it lands it adds one
  row on top of Part A's tile table (A5). Nothing in Part A has to be undone.

# Part A: Home screen

## A1. Layout (1280×720, UI scale `l`, nothing below the fold)

```
┌────────────────────────────────────────────────────────────────────────┐
│ READY                                                    status tile   │
│ Job: <mission> → <destination> · at Home · press Start   (small line)  │
│ <title / action of the top standing row>             [primary button] │
└────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────┬─────────────────┬───────────────────────┐
│ MODE                         │ SPEED           │ LINE POSITION         │
│ AUTO                         │ 0.00 m/s        │ +3 mm   [lcp bar]     │
│ Start runs the job           │ L 0.00 · R 0.00 │ LCP2 · level 7/7      │
└──────────────────────────────┴─────────────────┴───────────────────────┘
More ▸  (standing list; engineer: supervisor, readiness, At home, Recover…)
```

| Change | Detail |
|---|---|
| Job tile removed | The job becomes one small detail line inside the status tile (same text `job()` builds today) |
| Status tile | Full width. It merges `home-top`, `home-act` and `home-pos`: big state, job line, title/action, one primary button |
| RFID and Marker tiles removed | RFID was dropped on both vehicles (2026-11-05). The marker reading moves to the engineer's More block |
| Mode tile | Wide, beside Speed (3fr : 2fr, Speed at least 16rem); Line position full width under them (owner, 2026-11-12: "MA…" was cut on the HMI) |
| Speed and Line position | Unchanged |
| Web **At home** button | Small card at the top right of the status tile (Position status + At home), every role (owner, 2026-11-12). The panel combo does the same (A2) |

## A2. Status tile: one state, decided server-side

A new pure `alarms.home_tile(state, rows)` returns
`{kind, level, blink, big, job, title, action, button, steps, since_s}`. `/api/alarms` carries it next to
`headline`, and the page only draws it, as today. The first matching row wins:

| # | Kind | When | Look | Big text | Body |
|---|---|---|---|---|---|
| 1 | `fault` | top row `clears_by` = `restart_service`, a supervisor FAULT or job FAULT, or an error-level row | **red** solid | NEEDS SERVICE / STOPPED: NEEDS YOU | title, action, primary button (Recover / Restart / Acknowledge) |
| 2 | `unlocalized` | LINE: position status Not set, Lost, Failed or Rechecking (`home_position`); NAVIGATION: localization not READY | **yellow, blinking** | NOT LOCALIZED | steps below |
| 3 | `stopped` | run or job in a hold | **yellow** steady | STOPPED · WILL RESUME / NEEDS YOU | cause and action |
| 4 | `attention` | nothing running, top standing row at WARN (e.g. `SAFETY_RESET_NEEDED`, `DRIVES_NOT_READY`) | **yellow** steady | ATTENTION | title, action, primary button |
| 5 | `running` | run EXECUTING / line RUNNING | **green** | RUNNING | job and progress |
| 6 | `ready` | base ready, no row at WARN or above | **green** | READY | job line, "press Start" hint |
| 7 | `starting` | STARTING, TRANSITIONING, base not ready, panel stale | **grey** | NOT READY / connecting… | reason |

Unlocalized steps (LINE), ticked from what the PC can see:
1. Turn the selector to **MANUAL**. This is ticked from `PanelState.mode_auto`. The combo is refused under AUTO (`home_combo`).
2. Drive the vehicle to **HOME**. This can't be ticked: no sensor says "at HOME", which is why the press exists.
3. Hold the **yellow RESET** and **green START** together for 1 s.

After the press the tile shows "Checking position…" (steady yellow), then READY in green. A FAILED check
goes back to blinking with the check's reason. In NAVIGATION the steps instead point to Set position
(existing button).

Blink: 1 Hz. The background alternates between `--hazard` and `--hazard-wash`, and the text stays
`--hazard-ink`, so it is readable in both phases. It stays well under the 3 Hz flash limit. Under
`prefers-reduced-motion` it is steady with a thick border.

**E-stop without the wiring.** The PC still cannot see the E-stop itself. It sees the result, and the tile
shows that with the catalogue's existing words. It never shows a red EMERGENCY tile without the signal:

| Situation | What the PC sees today | Tile |
|---|---|---|
| E-stop during a run (LINE or NAVIGATION) | torque lost, field clear → hold `estop` | `stopped`, yellow: "Stopped: emergency stop or safety chain. Release the E-stop, then press Reset and Start." |
| E-stop while idle | drives in Switch on disabled → `SAFETY_RESET_NEEDED` / `DRIVES_NOT_READY` (WARN) | `attention`, yellow: "Motors are off: the safety circuit needs a reset. Press the yellow Reset button." |
| Panel / DIO not answering | `PANEL_STALE` (ERROR) | `fault`, red |

The `attention` row closes a hole: today's `headline()` falls through to READY when the top row is only a
WARN, which would put a **green** tile over "motors off". Green now requires no row at WARN or above.
A test pins both E-stop rows above.

## A3. Mode tile: colours

| Mode | Look | Sub line |
|---|---|---|
| **AUTO** | solid **blue** (`--accent-2` #2F5F94), white text | "Start runs the job" / station calling on |
| **MANUAL** | **white** tile, 3 px dark (`--ink`) border, dark text | "Manual Arm on / off" (DI08) |
| unknown | grey, "—" | "panel not read" |

Why: red, yellow and green belong to the status tile and keep their IEC 60073 meanings (emergency,
abnormal, normal). If the mode used one of them, "AUTO in green" next to a yellow stop would read as
"fine". Blue is the IEC colour for a mandatory or attention state, which fits "this vehicle may move on
its own". MANUAL is the neutral one, because a person is in control. Fill versus outline also tells the
two modes apart without relying on colour.

## A4. Code

| File | Change |
|---|---|
| `amr_web/alarms.py` | `home_tile()` (pure, table-tested); `home_position` stays as its input |
| `amr_web/server.py` | `/api/alarms` adds `tile` |
| `templates/home.html` | top rebuilt: status tile + three-column live row; `job()`, RFID and marker code removed; At home and marker moved into More |
| `static/amr.css` | `.home-tile.{ready,running,stopped,attention,unloc,fault,starting}`, `.blink` keyframes, `.mode-tile.{auto,manual}`; `.home-job`/`.home-top` removed; reuse `.live` |
| Tests | `home_tile` priority table (each row, plus a tie case per adjacent pair, plus the two E-stop situations above: never green, never red); `test_operator_ux`: no RFID/marker/job tile, the tile kinds render, fits at `l` |

Python, templates and static files are symlinked, so this needs a service restart only, with no colcon build.
Acceptance (operator, on the vehicle):
1. READY is green; AUTO and MANUAL follow the selector (blue / white).
2. After a restart, NOT LOCALIZED blinks. Selector to MANUAL (step 1 ticks), at HOME hold yellow + green
   for 1 s → Checking → READY in green.
3. A stop on tape: yellow STOPPED; the field clears → it resumes and goes back to green.
4. E-stop while idle: yellow ATTENTION "press Reset", **not** green. Reset → green.
5. Everything fits at UI scale `l`, with nothing below the fold.

## A5. What Part B adds later (no Part A rework)

- One row **above** `fault` in A2: kind `emergency`, red, kyb's banner content (EMERGENCY STOP, since
  mm:ss, steps ticked live, RESET_FAILED text), when `PanelState.emergency` ≠ NORMAL on a fresh panel.
- `base.html` banner on every other page, hidden on Home so the stop is not shown twice.
- The two E-stop situations above then show red with real steps. The `stopped`/`attention` rows stay for
  every other cause.
- The `.home-tile.emg` CSS class comes with Part B, not now.

# Part B: Emergency suite (POSTPONED until the Q3 wire)

## 1. Goal

When the E-stop is pressed, the controller must **know** it from a signal. Today it guesses from the
drives losing torque. With the signal it reacts the same way in every mode (LINE, MAPPING,
NAVIGATION). It also shows one red banner with numbered recovery steps on every web page:
**release the E-stop, press Reset, press Start**.

Nothing in the safety function changes. The Flexi Soft still takes STO (Q1/Q2 → HWTO1/HWTO2) in
hardware. The PC only reads a status bit, to explain the stop and to add more no-motion layers.
Reaching NORMAL never grants motion: Start (AUTO) or the manual lease (MANUAL) is still needed.

## 2. What kyb has that gvievo-01 lacks

| | gvievo-01 today | kyb-trackless |
|---|---|---|
| E-stop signal to the PC | **none**. Flexi Soft Q3 is "not connected" (`io-mapping.md` §2) | Q3 → DI08, HIGH = no emergency |
| How the PC knows | guesses: torque lost and field clear → hold `estop` (`amr_line/job.py`, `mode_fsm`, `readiness`) | `amr_base/emergency.py` state machine, published in `PanelState` |
| Display | an `ESTOP` alarm row, "Stopped: emergency stop or safety chain" | a full-width red banner on every page, with a timer and steps ticked as they are done; headline **EMERGENCY STOP**; jog and Start refused with 409 |
| Released vs still pressed | cannot tell | can tell (with an unlatched Q3) |
| Field stop reported late, looks like an E-stop | race logic `_estop_was_field` | resolved directly: DI stayed HIGH, so it was not the E-stop |

**The software cannot be ported without the wire.** A banner driven by the torque guess would also
show on a field or EDM trip, and it could never tick "released". So this plan does not ship an
interim banner without the signal.

## 3. Hardware and Flexi Soft (P0, owner/integrator, blocks vehicle use)

| Item | Decision |
|---|---|
| Wire | Flexi Soft **Q3 → DI09** (free; DI08 is already Manual Arm here). Terminal numbers «TB?» |
| Q3 logic | **E-stop OK only**: both E-stop channels (I1/I2) closed. **Not** the scanner OSSD: a field stop must not raise the banner, and the field auto-resume must keep working |
| Q3 latching | **Unlatched**: Q3 follows the button. This gives the PC the "released, press Reset" step. `emergency.py` handles a latched Q3 too, but then it cannot tell the operator "released" |
| Test pulses | **Off** for Q3: it feeds a standard DI. kyb found single LOW scans from test pulses, which `estop_low_scans` filters |
| Validation | Changing the Flexi Soft project means re-verifying the safety functions after the download (E-stop, protective field, SLS/standstill) and keeping a record. This is your or the integrator's procedure, outside this repo |
| Drawings | `io-mapping.md` §2/§4 and the JIS sheet for Q3/DI09 (follow the electrical workflow in `documentation/electrical/agent/SKILL.md`) |

Bench check after wiring: press and release the E-stop, then press Reset. Log DI09, DI01 and both
statuswords at 20 Hz with read-only tools while the service is stopped. That settles the reset
timeout (kyb uses 3.0 s).

## 4. Policy (carried from kyb owner answers, 2026-10-30)

These are assumed to apply to this vehicle as well (same owner):
- While not NORMAL, **every DIO output is LOW** (DO0/DO1 horn sounds, DO8).
- An emergency **never ends a run**. A moving run (pre-move included) goes into the `estop` hold.
  Other holds are relabelled `estop`. READY, PAUSED and waiting steps keep their state.
- Resume: after NORMAL, the operator presses **Start**. The pre-move warning runs, then the run continues
  from the step where it stopped. Reset alone never moves anything.
- Start/Load are refused while not NORMAL, at once, with no pre-move.
- **Physical Reset only.** No web Reset button and no API for it.
- Survey moves end on an emergency, but the mapping session does not.
- `auto_resume_estop` stays false. With the real signal, the profile refuses `true`.

## 5. Port strategy

Port by hand; don't cherry-pick. The branches diverged at 233c07a (2026-10-18). kyb removed LINE,
commissioning and RFID. main added station call, the position engine and NORMAL+.
- **Copy verbatim**: `amr_base/emergency.py`, `test/test_emergency.py`, the web functions in
  `amr_web/alarms.py` (`emergency`, `emergency_refusal`, `banner`, the standing order and the headline),
  the banner block in `base.html`, `emgBanner`/`emgLayout` in `amr.js`, and the `.emg-*` CSS.
- **Use the same contract** as kyb so a later merge stays mechanical: `PanelState.estop_ok`,
  `PanelState.emergency`, `EMG_NORMAL..EMG_RESET_FAILED = 0..4`, and alarm codes `ESTOP`,
  `ESTOP_RESET_NEEDED`, `ESTOP_RESET_FAILED`, `ESTOP_HOLD`.
- **Write new for gvievo-01**: the LINE path (`amr_line`), `mode_fsm`/`readiness`, the station
  bridge status, and the different DI numbers (Reset DI01, arm DI08, E-stop DI09).

## 6. Work packages

| WP | Content | Notes |
|---|---|---|
| E0 | Hardware and Flexi Soft (§3) | Blocks E8 only; E1–E7 run in sim |
| E1 | Contract: `PanelState` fields (append), profile `panel.di_estop_ok: 9`, `estop_low_scans: 2`, `estop_reset_timeout_s: 3.0`; schema, `_validate` (channel distinct from reset/start/auto/arm, required while `panel.enabled`), refusal tests in `tests/test_config.py`; alarm catalogue rows; `EXPECTED_CHECKS` bump | `amr_interfaces` change → clean `colcon build` and full service restart |
| E2 | `emergency.py` + table tests (verbatim) | Pure, clock-fed |
| E3 | `panel_io` / `panel_node`: DI09 filtered (LOW after `estop_low_scans`; invalid or stale = ACTIVE at once), run the FSM, log every transition, all outputs LOW; `fake_panel_node` E-stop toggle | |
| E4 | No-motion layers: `arm_policy` (no power while not NORMAL); `gating.select` → `NONE`, `code="ESTOP"` ahead of every source; mux ramp/S-curve state zeroed while inhibited; pendant must be released once after NORMAL; supervisor withholds the lease | Safety-listed files: tests plus the failure mode and recovery in the summary. Touches the same ramp as the open `no_jerk` bug, so check both together |
| E5 | Runs: `route_executor_node` (hold `estop` from the panel field; torque guess kept only as the fallback when the panel is stale; Start refused); **`amr_line/job.py`**: cause `estop` from the panel, `_estop_was_field` race only on the stale-panel fallback; HIGH-speed resume logic unchanged; survey move abort; `mode_fsm`/`readiness` use the panel emergency first | LINE is new work: kyb has no tape mode |
| E6 | Web: adapter `emergency` in `state()`, banner on every page except Home (where the new `home_tile` kind `emergency` shows it, A5), headline EMERGENCY STOP, emergency row first and duplicate-cause rows suppressed, jog and run start → 409, jog pad greyed, IO page DI09 red with the derived state; `--emg-h` keeps the jog pad above the fold at 1280×720, UI scale `l` | Port `test_emergency_web.py`; `test_operator_ux` for the banner on every page |
| E7 | Docs: RUNBOOK §4 alarm table regenerated, an operator page section on recovery; station bridge reports the emergency as a vehicle status (MQTT payload field), no behaviour change | Run the station sim on a profile copy with calling off |
| E8 | Vehicle acceptance (§7), witnessed | Only after E0 |

## 7. Vehicle acceptance (wheels on the ground, area clear)

1. Idle, MANUAL: E-stop → banner on every page within 0.2 s, jog does nothing. Release, Reset →
   banner clears. Jog works only after the pendant has been released once.
2. Jogging with the pendant held: E-stop → stops on STO. Keep the pendant held through release and
   Reset. The vehicle must not move.
3. NAVIGATION run mid-route: E-stop → BLOCKED(estop) and the banner. Reset only: no motion. Start:
   pre-move warning, then the run resumes.
4. **LINE run on tape at HIGH**: E-stop → hold. Reset, then Start → resumes at NORMAL speed (HIGH dropped,
   as today after a real E-stop).
5. Start pressed with the E-stop in → refused at once, no pre-move.
6. Reset pressed with the E-stop in → no change; the banner keeps the "release" step.
7. Unplug the DI09 wire → EMERGENCY (fail-safe). Unplug the DIO Ethernet → PANEL_STALE, no motion.
8. Protective-field stop on tape and in NAVIGATION → **no** banner, and the auto-resume still works.
9. Station call: an emergency during a called trip shows on the bridge status. The order is not cancelled.

## 8. Order

Part A now (restart only, operator floor check A4). Part B waits for the wire: E0 → E1 → E2 → E3 → E4 → E5 → E6 → E7 → one clean build and
restart → unified sim once → E8.
