# Plan: straights at 0.72 m/s

Status: implemented, uncommitted and not live until a service restart. The owner chose on
2026-11-04 to go straight to 0.72 without the separate 0.60 stage in section 5. The STO
measurement in section 3 is still open. Written 2026-11-04 against `44f7951` plus the other agent's uncommitted
arc-angle edits. Vehicle: MCQ4-4, branch `kyb-trackless`.

**Goal.** Forward straights go from 0.60 to 0.72 m/s (+20 %). Arcs stay at 0.30 m/s. Manual
speeds, spins and the auto acceleration and braking rates do not change.

**Gain.** Calculated for `route-itg-02`, driving time only, without waits, holds or the final
crawl: 758 s at a true 0.60, 669 s at 0.72. That saves about 89 s (12 %), and 68 s of it comes
from the two long straights s5 and s24.

## 1. Existing problems this has to fix first

### 1a. The 3.0 m approach ramp caps every speed

- `approach_velocity_scaling_dist` is 3.0 m (commit `44f7951`). The local costmap is 5 x 5 m,
  confirmed live with `ros2 param get`, so RPP sees at most 2.5 m of path ahead.
- RPP logged this at 09:32:25 today (`~/.amr/logs/layer.log`):
  `approach_velocity_scaling_dist is larger than forward costmap extent, leading to permanent slowdown`.
- Expected effect: the speed is scaled by 2.5 / 3.0 = 0.83 everywhere. Straights run at about
  0.50 m/s and arcs at about 0.25 m/s.
- This is **calculated, not measured**. The warning text is confirmed. The factor comes from my
  recollection of RPP's formula, because the source is not on this machine. No route has run
  since that setting went live (last run summary: 2026-11-03 15:28).
- Raising only `VEHICLE_V_MAX` to 0.72 would therefore give about 0.60 m/s on the vehicle.
- The start-speed checks in `HARDWARE-TESTS.md` 4B (0.60 in 6.9 s, 0.30 before corners) should
  not pass as written until this is fixed.

### 1b. The taper only looks one step ahead

`_step_speed` compares against `chain[1]` only. On `route-itg-02`:

- s26 (13.2 m) is followed by s27 (0.2 m), then arc s28.
- During s26 the next step has the same speed, so there is no taper. During s27 only 0.2 m is left.
- The vehicle therefore enters s28 near full speed and is still slowing about 1.6 m into the arc
  today. At 0.72 that becomes about 2.35 m of the 4.71 m arc.

## 2. Changes

Motion numbers at the current `a_max` 0.1, `d_max` 0.125, `auto_jerk` 0.1:

| | 0.60 | 0.72 |
|---|---|---|
| Rest to full speed | 7.0 s / 2.1 m | 8.2 s / 2.95 m |
| Slowdown to 0.30 | 3.65 s / 1.64 m | 4.6 s / 2.35 m |
| Taper starts before arc (includes 0.3 s lead) | 1.82 m | 2.57 m (automatic, from `_taper_dist`) |
| 0.30 back to full speed | 4.0 s / 1.8 m | 5.2 s / 2.65 m |
| Shortest arc-to-arc straight that reaches full speed | 3.4 m | 5.0 m |

### Speed

| File | Change |
|---|---|
| `amr_navigation/route.py` | `VEHICLE_V_MAX = 0.72` |
| `amr_navigation/config/nav2_params.yaml` | `desired_linear_vel: 0.72` |

The editor shows the server's value, so only the `editor.js` fallback and the test harness change.

### Stop at the end of a chain (owner 2026-11-04: just adjust the limits)

| File | Change |
|---|---|
| `amr_navigation/config/nav2_params.yaml` | `approach_velocity_scaling_dist` 3.0 -> 3.4 m, just under the new reach |
| `amr_navigation/config/nav2_params.yaml` | local costmap `width` and `height` 5 -> 7 m (reach 2.5 -> 3.5 m) |

This removes the permanent slowdown and also returns arcs to a true 0.30 m/s.

The ramp's demand from 0.72 is 0.72² / 3.4 = 0.15 m/s², above the mux `d_max` 0.125, which stays
as it is. So the speed runs above the ramp for part of the stop. Simulated with the real
`scurve` at a 3.5 m ramp: at most 0.10 m/s above it, and 0.05 m/s at the endpoint, about 17 s after
the ramp starts. This models only the speed command, so stopping accuracy needs the field check
below.

Two side effects to watch: the costmap has 2 times the cells at 5 Hz, and obstacle marks beside
the vehicle stay in the map out to 3.5 m rather than 2.5 m. The auto map clear still removes those.

### Taper look-ahead (fixes 1b)

Walk the whole chain instead of `chain[1]`, adding step lengths until the first slower step, and
compare the summed distance with `_taper_dist`.

### Keep the slow things slow

| Item | Change | Why |
|---|---|---|
| Reverse | New `route.REVERSE_V_MPS = 0.30` in `compiler.py:202` and `editor.js`, replacing half of `linear_mps` | Otherwise a reverse rises to 0.36 m/s, and it has no scanner cover |
| Collision look-ahead | `max_allowed_time_to_collision_up_to_carrot` 1.07 -> 0.89 s | Keeps the 0.64 m distance agreed on 2026-11-03. At 1.07 s it becomes 0.77 m. In a 0.30 arc it falls from 0.32 to 0.27 m |
| Warning-2 stop | `scanner_fields.yaml` `stop_m` 0.40 -> 0.38 (software value, not a scanner setting) | Keeps today's 0.117 s latency margin before the protective field (see below) |

HOME straight legs use the same speed, so they also go to 0.72. Tell me if they should stay at 0.60.

### Already within limits, no change

| Check | At 0.72 m/s |
|---|---|
| Motor speed | 2292 rpm of 4000 |
| Warning-2 stop | 0.68 m/s² at `stop_m` 0.38; the drive ramp limit is 1.0 m/s² |
| Warning 1 slowdown to 0.36 | 0.54 m, plus about 0.09 m latency, within the 0.80 m to warning 2 |
| RPP look-ahead | Already at its 1.2 m cap |
| Scan spacing | 7.2 cm at 10 Hz (6.0 cm today); watch localization in the field |

## 3. Safety gate: STO stopping distance (open decision)

The protective field is unchanged at 0.50 m from the scanner. With the scanner at x = 0.964 and
the nose at 1.10 (footprint marked MEASURE), about 0.36 m of field remains ahead of the nose.

At 0.72 the kinetic energy is 44 % higher, so braking distance is too, with the trolley load on
top. I found **no recorded STO stopping distance at any speed**. The 0.85 m/s floor acceptance
was left open, and the RUNBOOK says to confirm the field is sized for the speed.

Proposed gate, before any 0.72 run with people nearby:
1. Trip the protective field with a test object at a marked spot, at 0.60, with and without the trolley.
2. Multiply by 1.44 to predict 0.72. Go ahead only if the prediction fits.
3. Repeat at 0.72 and record the result.

The pass limit is the owner's call. If it does not fit, the field must grow in Safety Designer
(humans only), or the speed stays lower.

## 4. Tests

Update pins:
- `test_route.py` (590-618)
- `test_nav2_params.py` (22-24)
- `test_route_executor_logic.py` (612-625, new taper 2.57 m)
- `test_server.py:591` and `test_editor_js.py:56,82`
- `editor_harness.js:18`

Add:
- `approach_velocity_scaling_dist <= width / 2`. This catches 1a, which the current test missed.
- A short straight between a long straight and an arc tapers on the long straight (1b).
- Reverse stays at 0.30 whatever `VEHICLE_V_MAX` is.

Then run all package tests, `tests/run_all.py` (update `EXPECTED_CHECKS`) and ruff.

Docs: `RUNBOOK.md` 312-326, `HARDWARE-TESTS.md` 277-281, comments in `nav2_params.yaml`,
`base.launch.py:155`, `scanner_fields.yaml:19`.

## 5. Order and activation

1. Wait for the other agent to commit. `route.py`, `test_route.py`, `RUNBOOK.md` and `editor.js`
   all have its uncommitted edits. Line 81 of `route.py` does not overlap them, but the reverse
   change touches `editor.js`.
2. Commit 1: taper look-ahead, 7 m costmap and 3.4 m ramp, still at 0.60. Run on the vehicle and
   confirm a true 0.60 and 0.30, plus stopping accuracy.
3. Section 3 gate at 0.60.
4. Commit 2: 0.72 and its companions.
5. Activate with `sudo systemctl restart amr.service`, parked with no run active. No rebuild is
   needed, since the install is symlinked and no message changes.

Field checks at 0.72, without then with the trolley:
- Cruise speed on s5 and s24.
- Speed at or below 0.30 at each arc entry, including s28.
- Peak cross-track, against the 0.10 m limit.
- Stop position at the waits (`goal_overshoot_m`).
- Warning-1 and warning-2 stops on a long straight.
- No localization alarms.

Rollback: revert commit 2 and restart.

## 6. Decisions

- **Decided.** Adjust the limits: 3.4 m ramp, 7 x 7 m costmap, `stop_m` 0.38 (owner 2026-11-04).
- **Open.** Accept the STO gate as written, and set its pass limit.
