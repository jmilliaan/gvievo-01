# Tracked speed plan: NORMAL 0.5 / HIGH 0.85, fail-safe high zones, SLAM redundancy

Status: PLAN, nothing implemented. Drafted 2026-10-08. Tracked (LINE) mode only.
Phase A runs without localization and is what goes on the floor first; phase B adds
SLAM/AMCL redundancy afterwards.

## 0. Decisions

| # | Decision | Source |
|---|---|---|
| D1 | NORMAL 0.50 m/s is the default; HIGH = 1.7 x NORMAL = 0.85 m/s | operator |
| D2 | No software gate on 0.85 m/s. The nanoScan3 field set is not validated for it (`lidar.zones_validated` false) and there is no encoder speed monitoring in the FX3 yet: protective field and STO stopping distance at 0.85 are a floor check before the first HIGH run | operator |
| D3 | Steering gains: NORMAL = today's corner set (K 25 / Kd 5), HIGH = today's cruise set (K 11.3 / Kd 0.94), interpolated on the current speed | operator |
| D4 | LINE deceleration at the follower's rate: mux `line_d_max` = drive decel (~1.0 m/s^2) | operator |
| D5 | HIGH is switched by outer/inner RFID tag pairs at each straight end, with an encoder distance budget. The single toggle tag is retired | operator |
| D6 | Corner radii 0.5-1.0 m; HIGH straights > 15 m | operator |
| D7 | Curve guard on the IMU gyro (MLS), wheel odometry as fallback | operator |
| D8 | Warning field 2 `stop_m` 0.47 -> 0.40 (latency margin before the protective field) | operator |
| D9 | Phase B: localization optional inside the LINE layer (profile flag); zones authored as a taped path in the route editor, bound to the map revision | operator |

**Principle: every failure ends at NORMAL.** HIGH needs every condition true at once;
any missed read, hold, stop, fault, stale input or guard trip drops to NORMAL, and
nothing but a fresh, correctly ordered zone entry raises it again. Nothing here is in
the safety path (scanner -> FX3 -> STO stays hardware); this only decides how fast the
follower asks to go.

## 1. Why sensor-only curve detection is a backstop, not the trigger

- The MLS looks `sensor_lookahead_m` = 0.1 m ahead of the axle: ~0.12 s of warning at 0.85 m/s.
- 0.85 -> 0.50 m/s takes >= 0.35 s / 0.24 m at the drive limit, ~1.35 m with the 2 s comfort ramp.
- Entering radius R the tape leaves the sensor's +/-100 mm after s ~ sqrt(2 R 0.1): 0.32 m at R 0.5, 0.45 m at R 1.0.
- Steady corner error is kappa / K, independent of speed (autopilot docstring):

  | R | K 25 (NORMAL) | K 11.3 (HIGH) |
  |---|---|---|
  | 0.5 m | 80 mm of 100 | 177 mm - track lost |
  | 1.0 m | 40 mm | 88 mm - marginal |

So HIGH must end **before** a corner by placement (phase A) or by position (phase B);
the curve guard only limits the damage when that fails. Note R 0.5 m is marginal even at
NORMAL with K 25: corner tracking at 0.5 m/s is the first floor check (section 7).

Literature behind the layers: error-magnitude speed adaptation (already in the
autopilot as `sr_*`), curvature from yaw rate kappa = omega/v, tape heading-angle sensing
(Naviq MTS160), course learning (Pololu LearnBot), curvature-based speed profiles.

## 2. Phase A0 - speed reversal (no new behaviour beyond the numbers)

| Item | Change |
|---|---|
| Profile | `auto_rpm` 1500 -> **1592** (0.50 m/s); `auto_slow_ratio` -> **`auto_high_ratio` 1.7** (in (1, 2], `AUTO_HIGH_RPM` <= `motor_max_rpm`); `k_ratio`/`kd` = 25/5 (NORMAL), new `high_k_ratio`/`high_kd` = 11.3/0.94; `slow_k_ratio`, `slow_kd`, `auto_slow_ratio`, `gain_blend_s` refused |
| Config | `AUTO_SLOW_RPM` -> `AUTO_HIGH_RPM` (derived); checks, comments, params view |
| `runtime.py` | name map: `AUTO_HIGH_RPM`, `HIGH_K_RATIO`, `HIGH_KD`; line-loss standstill ceiling keyed off NORMAL |
| `autopilot.py` (deliberate port edit) | `update(slow=)` -> `update(high=)`: cruise = `AUTO_HIGH_RPM` if high else `AUTO_RPM`. Gains **interpolated on the current base speed** between (NORMAL, K 25/Kd 5) and (HIGH, K 11.3/Kd 0.94) instead of the 0.4 s time blend: a 2 s high->normal ramp would otherwise carry K 25 near 0.85 m/s, past the yaw-slew limit the docstring warns about |
| Junction `slow_speed` (branch_latch) | means "no HIGH through this junction" |
| U-turn creep | `approach_mps` <= NORMAL |
| Mission validator | stop rate checked from the fastest reachable speed (HIGH if the mission has high zones) against drive decel: 0.85 m/s in 0.5 m = 2300 r/min/s <= 3200 |
| Mux (`cmd_mux_kinematics_node.py`) | `line_d_max` param, 0 = drive decel; LINE source only (like `line_alpha_max`). **Failure mode:** any LINE command drop (stale, hold, fault) decelerates at up to ~1.0 m/s^2 instead of 0.5 - harder, never longer. **Recovery:** none needed; `line_d_max: 0.5` restores today. Test next to the `line_alpha_max` test |
| `scanner_fields.yaml` | warning_2 `stop_m` 0.47 -> **0.40**. Direct entry at 0.85: 0.90 m/s^2 (< drive 1.0); at 0.50: 0.31 m/s^2. Change the Safety Designer notes with it (this file is a copy). `scanner_fields.*` rule: adjust its test, state failure mode (a stop now ends 7 cm before the protective edge; latency up to ~0.08 s at 0.85 is absorbed) |
| Encoder distances | U-turn approach travel, U-turn re-pass re-arm and every distance budget use wheel travel (`/wheel_states` counts, as `TagOdometer` does), not commanded speed: a warning-field hold no longer burns `max_approach_m` |
| U-turn spin budget | paused while the mux reports a warning-field hold, instead of faulting the turn |
| Wire / UI | `LineState` append `bool high_speed`, `string speed_reason`; Run tracked Speed tile NORMAL/HIGH + reason; `colcon build` |
| README | status table speeds; known gap: 0.85 not validated against fields/STO |

## 3. Phase A1 - fail-safe high zones (replaces the speed toggle)

### Layout

Each end of a HIGH straight carries a pair, ~0.3 m apart along the tape:

```
corner ... [O]--0.3 m--[I] ======== straight S1 (length L) ======== [I]--0.3 m--[O] ... corner
```

O = outer (corner side), I = inner (straight side). Order gives direction, so no route
knowledge is needed and the straight can be entered from either end.

### Mission schema (v2.1)

```json
"straights": [{"id": "S1", "length_m": 18.0}],
"tags": [
  {"tag": "«O1»", "action": "high_zone", "straight": "S1", "end": "A", "position": "outer", "ignore_s": 2},
  {"tag": "«I1»", "action": "high_zone", "straight": "S1", "end": "A", "position": "inner", "ignore_s": 2},
  {"tag": "«I2»", "action": "high_zone", "straight": "S1", "end": "B", "position": "inner", "ignore_s": 2},
  {"tag": "«O2»", "action": "high_zone", "straight": "S1", "end": "B", "position": "outer", "ignore_s": 2}
]
```

- `length_m` is surveyed inner-to-inner. The budget is **derived**, not typed:
  `high_for_m = length_m - brake_m - margin_m`, with `brake_m` = travel of the
  HIGH->NORMAL ramp ((0.85+0.50)/2 x `ramp_s`, 1.35 m at 2 s) and `margin_m` 1.0 m
  (profile `autopilot.high_margin_m`). Refused when `high_for_m` < 3 m (not worth it).
- Validator: each straight has exactly one O and one I per end; tags unique across the
  table; `speed_toggle` rows refused with a pointer to `high_zone`; `ramp_s` moves to the
  profile (`autopilot.high_ramp_s`, one value for the vehicle).

### Engine (`amr_line/speed_zone.py`, pure, clock- and odometry-fed)

| State | Event | Next | Note |
|---|---|---|---|
| NORMAL | O(end) read | ARMED(end) | arm expires after 1.0 m encoder travel |
| ARMED(end) | I of the same end | HIGH(budget) | ramp up over `high_ramp_s` |
| ARMED(end) | any other tag, or arm expiry | NORMAL | |
| HIGH | I read (any) | NORMAL | leaving: the inner tag comes first |
| HIGH | budget used up (encoder) | NORMAL | event "HIGH expired: end tag not reached" |
| HIGH | stop begins, U-turn, any HOLD, RFID link lost, Reset, new run, junction slow zone, curve guard trip, IMU+odometry stale | NORMAL | reason recorded |
| any | O read while HIGH | NORMAL | malformed order: never raise on doubt |

Missed-read outcomes, all at NORMAL or bounded:

| Missed | Result |
|---|---|
| O or I on entry | straight at NORMAL (slow, safe) |
| I on exit | budget expires `brake_m + margin_m` before the inner tag -> NORMAL before the corner |
| both exit tags | same |
| an O on exit | nothing: I already ended HIGH |

### Site table

`missions/line-a.json`: row `0040` (`speed_toggle`) is removed; four tags per HIGH
straight are added. Tag ids and lengths are `«placeholder»` until the tags are placed:
the mission is refused until they are filled in, never run with guesses.

## 4. Phase A2 - curve guard (backstop)

- **Signal:** kappa_hat = omega / v with omega from `/imu/data` (bias-corrected MLS gyro,
  `imu_bias_node`), fallback omega = (v_r - v_l) / track from `/wheel_states` when the IMU
  is older than 0.1 s; v from wheel odometry. Inactive below 0.2 m/s. Both stale -> HIGH
  refused (D-principle).
- **Second signal:** |lateral error| from the follower (> `curve_guard_e_mm`, default 40 mm).
- **Trip:** |kappa_hat| > `curve_guard_kappa` (default 0.25 1/m, R 4 m: well clear of
  straight-line wobble, well below the 1.0-2.0 1/m corners) sustained over 0.05 m of
  travel, or the error trip, while HIGH or ramping down.
- **Action:** NORMAL **at drive deceleration**, bypassing the 2 s comfort ramp; latched
  until the next valid O->I entry. Event + `speed_reason` "curve guard".
- **Independence note:** the gyro lives in the MLS, the same CAN device as the tape
  reading. An MLS failure already stops the follower (`sensor_lost`), so the guard is not
  needed then, but it is not independent of the MLS link.
- Profile keys (`autopilot.curve_guard_kappa`, `curve_guard_e_mm`) with schema, validation
  and refusal tests. Thresholds settled on the floor (section 7), not in sim.

## 5. Phase B - SLAM / RFID / line-sensor redundancy (after phase A is proven)

### Roles

| Decision | Line sensor | RFID | Localization | Rule |
|---|---|---|---|---|
| Steering | owner | - | - | unchanged |
| Exact stops | - | owner | cross-check | tag not read by its map position + margin -> HOLD (`rfid_tag_overdue`) |
| HIGH allowed | curve guard | zone pairs | zone [s_start, s_end] | HIGH only if **all available** agree |
| Slow before corner | - | exit pair, budget | zone end - brake - k*sigma | earliest wins |

### Mechanics

- **Layer:** profile `line.localization: true` + a bound map revision adds `map_server`,
  AMCL and `localization_monitor_node` to the LINE layer. No Nav2 controller, behaviors or
  executor. Flag off = today's LINE exactly.
- **AMCL for a vehicle on tape:** `max_particles` 2000 -> ~800, `update_min_d` 0.05 -> 0.15 m,
  `update_min_a` 0.03 -> 0.1 rad. Lateral is fixed by the tape; only along-track matters.
- **Taped path:** a polyline drawn on the map revision in the route editor, RFID tags placed
  on it; stored in the map bundle, so it moves with its revision. Loader refuses a path
  whose tags disagree with a new revision (loop closure / re-mapping protection).
- **Position along route s:** AMCL pose projected onto the path; direction from ds/dt;
  re-synced at each RFID read. Along-track sigma from the AMCL covariance projected on the
  path tangent.
- **Jump detection:** AMCL delta vs odometry delta > 0.15 m in one update -> untrusted until
  the next RFID re-sync.
- **Gate:** `amr_line/speed_gate.py`, pure: inputs s, sigma, jump flag, zone list, RFID
  zone state, curve guard; output NORMAL/HIGH + reason. A zone's HIGH end is pulled
  forward by `brake_m + k*sigma + latency`; when sigma makes a zone shorter than 3 m it
  stays NORMAL. Stale localization -> NORMAL, so CPU overload costs speed only.

### CPU

LINE today: ~2.6 of 4 N97 cores, 58 C (2026-10-08 sample). Estimated add: AMCL 10-25 % of a
core (tuned lower), monitor 5-10 %, gate negligible -> ~70-75 %. Free first:
`commissioning_node` (15 % idle in LINE), profile `web_node` (38 %). Go rule: measured
< 75 % total and < 75 C on a warm day.

### Measurement before building phase B

One stationary-then-slow LINE run with AMCL running beside it (temporary launch; needs a
service stop/start, only on the operator's go): `pidstat 5` for 15 min + AMCL along-track
error at every RFID read in the longest straight. sigma <= 0.2 m -> build as described;
worse -> SLAM is only the overdue-tag detector and corner backstop.

## 6. Failure modes and recovery

| Failure | Effect | Recovery |
|---|---|---|
| Missed zone tag | NORMAL earlier or budget expiry before the corner | none; next entry pair |
| Toggle-style inversion | impossible: no toggle state survives a miss | - |
| Curve entered at HIGH anyway | guard trips -> drive-decel to NORMAL; worst case tape lost -> `line_lost` -> DONE | operator re-places the vehicle; check tag placement |
| IMU and odometry stale | HIGH refused | automatic when fresh |
| Warning field at HIGH | mux factor ramp; warning-2 stop ends 0.07 m before protective | automatic when clear |
| Protective field at HIGH | STO (hardware) + software zero; stopping distance at 0.85 **unvalidated** | HOLD field, auto-resume 2 s |
| `line_d_max` drop to zero | stop at up to ~1.0 m/s^2 | - |
| Phase B: AMCL jump / lost / high sigma | NORMAL | RFID re-sync |
| Phase B: map revision changed | zones refused until the tape path is re-checked | operator re-binds |
| CPU overload (phase B) | localization stale -> NORMAL | automatic |

## 7. Tests and floor acceptance

Offline (focused, per CLAUDE.md): config refusals; mission v2.1 refusals; `speed_zone.py`
table above row by row; curve guard thresholds, fallback and staleness; autopilot gain
interpolation and `high=` default-equivalence; mux `line_d_max` vs other sources;
`scanner_fields` stop_m; encoder-distance U-turn approach under a simulated warning hold.
Unified sim once at the end of each phase.

Floor, in order - each step PASS when the operator saw it:

1. Corners at NORMAL 0.5 m/s with K 25 on the tightest radius (R 0.5 m is marginal by the
   kappa/K estimate).
2. Protective field + STO stopping distance from 0.85 m/s (D2) - before any HIGH run.
3. HIGH on the longest straight: ramp up/down 2 s, end before the corner by budget.
4. Each missed-tag case from section 3 by covering one tag at a time.
5. Curve guard: enter a corner deliberately at HIGH at a safe test corner; record kappa_hat
   and error traces; set thresholds.
6. Warning 1 / warning 2 at both speeds: stop position vs the protective edge.

## 8. Open items («measure» / «placeholder»)

- Tag ids and positions for every high-zone pair; `length_m` of each HIGH straight.
- Radius of each corner (tightest first).
- FX3/nanoScan3 validation at 0.85 m/s; later, encoder speed monitoring and speed-switched
  fields (then revisit D2 and D8).
- Phase B: CPU and along-track measurement (section 5).
