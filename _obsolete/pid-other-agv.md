# PID Steering Loop — AGV KIM2A Controller

**Audience:** a coding agent with prior PID / AGV experience but no context on this repo.
This document is self-contained: it describes the plant, the exact control law as
implemented, every tuned parameter with its live value, and the non-obvious behaviours
you would otherwise have to reverse-engineer.

Everything below is transcribed from the code, not from memory. Sources of truth:

| Thing | File |
|---|---|
| Control law | `core/pid.py` (`PIDController`) |
| Loop that drives it | `modes.py` (`auto_mode`) |
| Parameter loading + validation | `config.py` |
| Actual tuned values | `profiles/agv1_kim.json`, `profiles/agv2_kim.json` |
| rpm ↔ voltage motor map | `motion.py` |
| Sensor frames | `drivers/can_mgs1600.py` |
| Run logging (CSV + PNG) | `debugging/plotter.py` |

---

## 1. What the loop actually controls

This is a **differential-drive AGV following a magnetic tape**. There is no odometry in
the loop, no pose estimate, no path planner. It is a single SISO cross-track regulator:

```
process variable  pv  = lateral tape offset in millimetres, from an MGS1600 magnetic
                        tape sensor over CAN (frame field "left_mm", int16)
setpoint              = 0 mm  (implicit — never appears as a variable)
control output        = a wheel-rpm DIFFERENTIAL applied around a base rpm
```

The base rpm is **not** produced by this controller. It comes from an open-loop
acceleration ramp toward a target speed selected by the current speed mode. The PID only
steers; it never sets travel speed (except via the "speed reduction" term, §5).

Command chain per cycle:

```
left_mm (mm) → sanity/slew filter → PID → steering differential (rpm)
             → left_rpm / right_rpm → per-wheel affine inverse motor map → volts
             → analog output channels 0/1 (Modbus AO)
```

Wheel direction is a separate digital output; the analog channel carries **speed
magnitude only**. `rpm_to_voltage()` returns `0.0 V` for any `rpm <= 0`, so a wheel
commanded negative simply **stops** — it does not reverse. That is an important
non-linearity at large steering outputs (§9).

### Sign conventions — get these right first

```
e = error_sign * pv           error_sign = -1.0   (forward auto — the only mode that runs)
```

* Positive `pv` (`left_mm > 0`) → tape lies to the AGV's **left** → the AGV has drifted right.
* Positive `pv` → `e` negative → `output` negative → `left_rpm` down, `right_rpm` up →
  **yaw left**, back toward the tape. Correct.
* **Positive `output` = yaw right.** This matters for the asymmetric APPROACH clamp (§6).

`error_sign = +1.0` exists in the `compute()` signature for a rear-sensor reverse mode
(geometry inverted). No caller uses it today — `auto_mode` hardcodes `-1.0`. See §9 for a
latent sign bug on that path.

---

## 2. The control law, exactly as implemented

ISA / "ideal" dependent form — `Kp` multiplies all three terms:

```
u = Kp·e  +  Kp·(1/Ti)·∫e dt  +  Kp·Td·(de/dt)      [filtered, taken on the measurement]
```

Condensed from `core/pid.py: compute()`:

```python
e = error_sign * pv

# measured loop period, not nominal DT
now = time.perf_counter()
dt  = self._dt if self._last_t is None else clamp(now - self._last_t,
                                                  0.2*self._dt, 5.0*self._dt)

# P
p_term = self._kp * e

# I — accumulates ONLY INSIDE the deadband, then hard-clamped
if abs(e) < self._ti_deadband:
    self.integral += e * dt
    self.integral  = clamp(self.integral, -self._ti_max, +self._ti_max)
i_term = self._kp * (1.0 / self._ti) * self.integral

# D — first-order low-passed, taken on PV (not on e)
alpha            = dt / ((self._td / self._n) + dt)
raw_d            = -self._kp * self._td * ((pv - self.last_pv) / dt)
self.filtered_d += alpha * (raw_d - self.filtered_d)

# clamp applies to the PID output ONLY
output       = clamp(p_term + i_term + self.filtered_d, self._clamp_lo, self._clamp_hi)
output_total = output + feedforward          # feedforward is NOT clamped

# speed reduction (see §5)
raw_sr = min(abs(e * self._v_red_coef) + abs((pv - self.last_pv)/dt) * 0.5,
             base_rpm * self._sr_cap)
self.speed_reduction += self._sr_alpha * (raw_sr - self.speed_reduction)

left_rpm  = base_rpm - self.speed_reduction + output_total
right_rpm = base_rpm - self.speed_reduction - output_total
self.last_pv = pv
```

`compute()` returns `(left_rpm, right_rpm, debug_dict)`, the debug dict carrying
`e, p, i, d, output, feedforward, output_total, speed_reduction`.

### Four things that differ from a textbook PID

1. **The integral deadband is inverted from the usual meaning.** It integrates only when
   `|e| < TI_DEADBAND` and **freezes outside** it. This is deliberate: it is conditional
   integration used as anti-windup. Large excursions (corner entry, tape reacquire)
   contribute nothing to the integrator; the integrator exists solely to null small
   standing biases near the tape. Do not "fix" this into a conventional deadband.

2. **Derivative on measurement, with the sign baked in.** `raw_d` uses `-Kp·Td·Δpv/dt`,
   which equals `+Kp·Td·de/dt` only because `error_sign == -1`. The setpoint is constant
   at 0, so there is no derivative kick from setpoint changes — but there is one after a
   `last_pv` reset (§9).

3. **`dt` is measured, not assumed.** The loop is event-driven on CAN frames and jitters,
   so `perf_counter` deltas are used, clamped to `[0.2·DT, 5·DT]` = **[2 ms, 50 ms]**. A
   scheduling hiccup or a resume-after-stop gap therefore cannot blow up the I and D
   terms. `alpha` is recomputed every cycle from the measured `dt`, so `update_gains()`
   has nothing to precompute.

4. **Feedforward bypasses the output clamp** and is added after it. The clamp limits
   *feedback* authority; the feedforward is a known-good geometric command (§4). The
   final safety net still exists downstream: per-wheel voltage is clamped to `[0, 5] V`.

---

## 3. Gain scheduling — three gain sets, switched by speed mode

`state.speed_mode` is one of `HIGH` / `SLOW` / `APPROACH`, set by the RFID-driven
sequence engine (`core/sequence_engine.py`). `auto_mode` calls `pid.update_gains(...)`
**only on a mode change**, and `update_gains()` deliberately **does not reset** the
integrator or the derivative filter, so the switch is bumpless.

| Mode | When | Target speed (agv1) | Gains |
|---|---|---|---|
| `HIGH` | straights | 0.32 m/s | `KP`, `TD`, `N`, `V_RED_COEF`, symmetric clamp |
| `SLOW` | corners / caution zones | 0.18 m/s | `KP_SLOW`, `TD_SLOW`, `N_SLOW`, `V_RED_COEF_SLOW`, symmetric clamp |
| `APPROACH` | station crawl into a guide bar | 0.18 m/s | `KP_APPROACH`, `TD_APPROACH`, `N_APPROACH`, `V_RED_COEF_APPROACH`, **asymmetric** clamp |

The PID object is **constructed with the SLOW gain set** and switches on the first cycle
if the mode is anything else.

House convention (also stated in `project_overview.md`): **`KP` scales roughly linearly
with target speed.** If you change a target speed, scale that mode's `KP` with it as the
first guess.

---

## 4. Curvature feedforward (lives in `modes.py`, not in the PID class)

A pure feedback loop must hold a standing cross-track error to sustain a turn. The
geometric differential for a constant-radius arc is fed forward instead:

```
ff_target    = FF_SCALE · FF_DIRECTION_SIGN · 0.5 · base_rpm · (TRACK_WIDTH / CURVE_RADIUS)
ff_filtered += FF_ALPHA · (ff_target − ff_filtered)        # smooths corner entry/exit
```

* Gated on `config.FF_ENABLED and state.nav_in_corner`. `nav_in_corner` is true **only
  while a NAV-category sequence holds `SLOW`** — a station approach that happens to use
  `SLOW` does *not* get feedforward (the engine clears the flag for SEQ sequences).
* `FF_DIRECTION_SIGN = -1.0` for a left turn (this track is a CCW stadium, all lefts).
  Turn direction is fixed in config; there is no per-corner detection.
* Magnitude is proportional to `base_rpm`, so it auto-scales with corner speed. `FF_SCALE`
  is the hand-tuned trim (0.85 on agv1, empirically reduced from 1.0).
* Numeric example (agv1, SLOW = 0.18 m/s → base ≈ 573 rpm):
  `0.85 · (−1) · 0.5 · 573 · (0.46 / 1.5) ≈ −74.7 rpm` steering differential.

---

## 5. Speed reduction — the loop's only speed authority

```
raw_sr = min( |e·V_RED_COEF| + |Δpv/dt|·0.5 ,  base_rpm · SR_CAP )
speed_reduction += SR_ALPHA · (raw_sr − speed_reduction)
left/right = base_rpm − speed_reduction ± output_total
```

Both wheels slow proportionally to how far off-track the AGV is **and** how fast it is
moving laterally, so it crawls through a bad correction instead of taking it at full
speed. Notes:

* The lateral-rate half uses a **hardcoded 0.5** and is **not** scaled by `V_RED_COEF`.
  Only the position half responds to that parameter.
* The cap is applied to the **raw** value before filtering, so `speed_reduction` can
  never exceed `SR_CAP · base_rpm` (45 % of base on agv1).
* `SR_ALPHA = 0.15` is a plain first-order lag on the reduction, not on the error.
* This term is **always** subtracted, in every mode. On `APPROACH`,
  `V_RED_COEF_APPROACH` is dropped to 0.4 precisely so the station crawl is not slowed
  further.

---

## 6. The asymmetric APPROACH clamp (the least obvious design decision)

Normally the clamp is symmetric: `±OUTPUT_CLAMP_RPM`. In `APPROACH` the AGV crawls into a
station where a **one-sided physical guide bar on the AGV's right** does the final
centring mechanically. So the clamp becomes:

```
clamp_hi = +OUTPUT_CLAMP_INTO_BAR_APPROACH  =  +8 rpm   (positive output = yaw right = INTO the bar)
clamp_lo = −OUTPUT_CLAMP_AWAY_APPROACH      = −80 rpm   (yaw left = OFF the bar)
```

The controller is deliberately made nearly powerless to press *into* the bar — the bar
absorbs that correction, and the PID pressing as well over-loads the bearings — while
retaining authority to recover *off* it. `KP_APPROACH` is also dropped to 0.45: the tape
is straight here, so little feedback authority is needed.

Per the profile comment, **`OUTPUT_CLAMP_INTO_BAR_APPROACH` is the tuning dial**: lower it
toward 0 if the AGV still binds against the bar; raise it if the AGV drifts left off the
bar.

---

## 7. Loop structure and safety interlocks (`modes.py: auto_mode`)

Per iteration, in order:

1. **Emergency** → `motion.idle()` (brakes *released*, so the AGV can be pushed by hand),
   ramp speed to 0, `pid.reset()`, clear `ff_filtered`, `continue`.
2. **Sequence stop** → `motion.set_brake()`, ramp to 0, `pid.reset()`, hold.
3. Pick `target_speed` from `speed_mode`; call `update_gains()` **only if the mode changed**.
4. **Drain `state.sensor_queue`, keeping only the newest frame** — the controller never
   acts on a stale frame and a backlog cannot build up.
5. If no fresh frame this iteration: **skip the PID entirely**; the analog outputs hold
   their previous value. `dt` on the next real cycle absorbs the gap (clamped at 5·DT).
6. **Tape loss** (`tape_detected == False`) → brake, ramp to 0, `pid.reset()`, latch
   `tape_was_lost`; on reacquire, re-arm forward at 0 rpm and ramp again.
7. Accel / decel ramp on `current_target_speed` (`ACCEL_RATE`, `DECEL_RATE`, or the
   gentler `APPROACH_DECEL_RATE` while in `APPROACH`), then `base_rpm = mps_to_rpm(...)`.
8. **Sensor sanity + slew limit** — `|pv| > SENSOR_MAX_MM` (100 mm) → the frame is
   **discarded** and the command held. Otherwise `|pv − last_valid_pv| > SENSOR_MAX_STEP_MM`
   (40 mm) → `pv` is **clamped** toward the last accepted value. Both guards exist because
   a single glitch frame would otherwise jerk the steering hard through the D term.
9. Feedforward, then `pid.compute()`, then per-wheel `rpm_to_voltage()` → AO 0 / AO 1.
10. Record a sample for the run plot; log a throttled debug line every 25 cycles (a stray
    console DEBUG level at 100 Hz would otherwise flood).
11. **CAN timeout** (`> CAN_TIMEOUT`, 0.5 s since the last frame) → brake + `pid.reset()`.

Nominal cadence is `await asyncio.sleep(config.DT)` = 10 ms (100 Hz), but the real period
is whatever the frames and the event loop deliver — hence the measured `dt`.

**Every stop path calls `pid.reset()`**, which zeros `integral`, `last_pv`, `filtered_d`,
`speed_reduction`, and `_last_t`. There is no bumpless-restart handling beyond that (§9).

---

## 8. Parameter reference — live values

The `AGV_ID` env var selects `profiles/{AGV_ID}.json` (default `agv1_kim`). `config.py`
range-checks the critical parameters at import and raises `ConfigError` — the controller
refuses to boot on a bad profile rather than dividing by zero mid-motion.

**agv1_kim is the current, actively tuned unit.** agv2_kim is an older second unit with no
`APPROACH` mode and feedforward disabled; it is shown for contrast only.

### PID gains

| Param | agv1 | agv2 | Meaning |
|---|---|---|---|
| `KP` | 2.8 | 1.4 | HIGH-speed proportional gain (rpm per mm) |
| `TD` | 0.26 | 0.12 | HIGH derivative time (s) |
| `N` | 20 | 20 | HIGH derivative filter ratio → filter τ = `TD/N` = 13 ms |
| `KP_SLOW` | 2.6 | 2.2 | corner gain |
| `TD_SLOW` | 0.16 | 0.14 | corner derivative time (τ = 13.3 ms) |
| `N_SLOW` | 12 | 12 | corner filter ratio |
| `KP_APPROACH` | 0.45 | — | station-crawl gain, deliberately weak |
| `TD_APPROACH` | 0.2 | — | station-crawl derivative time |
| `N_APPROACH` | 10 | — | station-crawl filter ratio (τ = 20 ms) |
| `TI` | 25 | 20 | integral time (s) — **shared across all modes** |
| `TI_DEADBAND` | 20 | 25 | integrate only while `\|e\|` is **below** this (mm) |
| `TI_MAX` | 400 | 500 | integrator clamp (mm·s) → max I contribution `Kp·(1/Ti)·TI_MAX` ≈ **44.8 rpm** |
| `DT` | 0.01 | 0.01 | nominal loop period (s); also the `dt` clamp reference |
| `OUTPUT_CLAMP_RPM` | 1000 | 800 | symmetric PID output clamp (rpm) |
| `OUTPUT_CLAMP_INTO_BAR_APPROACH` | 8 | — | APPROACH clamp toward the guide bar |
| `OUTPUT_CLAMP_AWAY_APPROACH` | 80 | — | APPROACH clamp away from the bar |
| `V_RED_COEF` | 2.8 | 4 | speed-reduction gain, HIGH |
| `V_RED_COEF_SLOW` | 2.0 | 2 | speed-reduction gain, SLOW |
| `V_RED_COEF_APPROACH` | 0.4 | — | speed-reduction gain, APPROACH |
| `SR_ALPHA` | 0.15 | 0.15 | low-pass on the speed reduction |
| `SR_CAP` | 0.45 | 0.55 | speed reduction ≤ this × `base_rpm` |

Scale check on agv1 at HIGH: `base_rpm ≈ 1019 rpm` at 0.32 m/s. A 20 mm error gives
`P = 56 rpm` (~5.5 % differential), so `OUTPUT_CLAMP_RPM = 1000` is a runaway guard, not
an active limit. The D term dominates transients: `Kp·Td = 0.728` rpm per (mm/s), and the
filter passes `alpha = 0.01/(0.013+0.01) ≈ 0.43` of each new sample.

### Speeds and ramps (agv1)

| Param | Value | Notes |
|---|---|---|
| `AUTO_TARGET_HIGH_SPEED` | 0.32 m/s | ≈ 1019 motor rpm |
| `AUTO_TARGET_SLOW_SPEED` | 0.18 m/s | ≈ 573 motor rpm |
| `AUTO_TARGET_APPROACH_SPEED` | 0.18 m/s | station crawl |
| `ACCEL_RATE` | 0.5 m/s² | applied as `rate · DT` per cycle |
| `DECEL_RATE` | 0.5 m/s² | |
| `APPROACH_DECEL_RATE` | 0.4 m/s² | gentler, so the RFID-armed slow-down is smooth |
| `MANUAL_TARGET_HIGH/SLOW_SPEED` | 0.3 / 0.2 m/s | pendant jog — no PID involved |

### Sensor limits (agv1)

| Param | Value | Notes |
|---|---|---|
| `SENSOR_MAX_MM` | 100.0 | frames beyond this are discarded (sensor half-width ≈ 80 mm) |
| `SENSOR_MAX_STEP_MM` | 40.0 | per-cycle jumps larger than this are clamped, not discarded |
| `CAN_TIMEOUT` | 0.5 s | no frame for this long → brake + PID reset |

### Feedforward (agv1)

| Param | Value |
|---|---|
| `FF_ENABLED` | 1 (0 on agv2) |
| `TRACK_WIDTH_M` | 0.46 (wheel centre-to-centre) |
| `CURVE_RADIUS_M` | 1.5 |
| `CURVE_DIRECTION` | `left` → `FF_DIRECTION_SIGN = −1.0` |
| `CURVE_SPEED_MODES` | `["SLOW"]` |
| `FF_ALPHA` | 0.15 |
| `FF_SCALE` | 0.85 |

### Kinematics and motor map (agv1)

```
WHEEL_DIAMETER = 0.18 m,  GEAR_RATIO = 30
motor_rpm = (v_mps · 60 / (π · 0.18)) · 30

per-wheel affine map, from an encoder calibration run (R² = 0.99 for V ≥ 0.55):
  left :  rpm = 1295.0·V − 354.2
  right:  rpm = 1289.8·V − 299.1
the inverse is clamped to [0, 5] V;  rpm ≤ 0 → 0 V
```

The left and right maps differ by ~6 %. Using the side-aware inverse is what removes the
straight-line drift — **the PID is not correcting a systematic L/R mismatch**, the motor
map is. If you ever collapse these back to a single fit, expect a standing bias that the
integrator will have to fight.

---

## 9. Gotchas — read before changing anything

1. **Derivative kick on every restart.** `reset()` sets `last_pv = 0.0`. The first
   `compute()` after any stop therefore sees `Δpv = pv − 0` over a nominal 10 ms `dt`. At
   agv1 HIGH gains with a 10 mm standing offset that is `raw_d ≈ −728 rpm`, and the filter
   still passes ~43 % of it (`≈ −317 rpm`) into the first output. It sits inside the ±1000
   clamp, so nothing catches it. It is survivable in practice only because the AGV
   restarts from `base_rpm ≈ 0` on the ramp — if you ever raise the resume speed, prime
   `last_pv` with the first live sample instead.

2. **`error_sign` is not applied to the D term.** `raw_d` hardcodes the negative sign,
   correct only for `error_sign = −1` (forward). If the reverse mode the docstring
   describes is ever wired up with `error_sign = +1`, the derivative becomes **positive
   feedback**. Latent, not active — no caller passes `+1` today.

3. **`update_gains()` intentionally does not reset state.** The integrator carries across
   a HIGH→SLOW switch. Since `TI` is shared and `Kp` changes, the *contribution* of a
   stored integral jumps by the `Kp` ratio at the switch — small here (2.8 → 2.6), large
   into APPROACH (2.8 → 0.45, which shrinks it). Keep this in mind if you widen the gain
   spread.

4. **Feedforward is outside the clamp by design.** Do not "tidy" it inside; that was a
   deliberate decision, documented in `pid.py` and `project_overview.md`.

5. **The integral deadband is conditional-integration anti-windup, not a deadband.** See
   §2.1. Inverting it would let the integrator wind up through every corner.

6. **A negative wheel rpm becomes 0 V, not reverse.** At large `output_total` the inner
   wheel saturates at a stop and the differential stops being linear in `output`. The
   speed-reduction term makes this more likely, since it lowers `base_rpm` first.

7. **The loop is frame-driven.** No fresh CAN frame → no PID cycle → the previous analog
   output is held. Do not assume a fixed 100 Hz when reasoning about the I term; the
   measured `dt` handles it, but any code you add that assumes `DT` will drift.

8. **`sensor_failure` is not acted on.** The CAN frame carries a `sensor_failure` flag
   (`FLAG_SENSOR_FAIL`), but `auto_mode` only checks `tape_detected`; the failure flag is
   merely surfaced to the web UI (`app/app.py`). A failing-but-still-reporting sensor will
   not stop the AGV on its own.

9. **`config.py` validates at import time.** Anything you add to `pid_tuning` should get a
   `check(...)` line in `_validate()` — the existing ones guard divide-by-zero (`TI`,
   `N*`, `DT`) and runaway (clamps, speeds).

10. **Two profiles exist and they are not interchangeable.** agv2's motor calibration
    (`646.59 / −101.2`) is the superseded single fit that was ~2× too low, and its gains
    are tuned against that wrong map. Do not port agv2 gains onto agv1 or vice versa.

---

## 10. How to observe and tune

* **Per-run data.** `debugging/plotter.py: RunRecorder` is started and stopped around
  `auto_mode` and writes, per AUTO run, into `analysis_plot/`:
  * `YYYYMMDD_HHMMSS_data.csv` — columns `time_s, error_mm, left_rpm, right_rpm,
    pid_output, d_term`
  * `YYYYMMDD_HHMMSS_analysisplot.png` — left/right rpm on one axis, tracking error
    (−100…+100 mm) on the other, versus time
  * Toggle with `PLOTTING_ENABLED` at the top of that file; `False` means zero overhead
    and matplotlib is never imported.
  * The directory already holds many historical runs — useful as before/after references
    for a tuning change.
* **Live line.** `auto_mode` logs every 25 cycles at DEBUG:
  `[MODE] Target=…m/s e=…mm P=… I=… D=… out=… L=… R=…rpm Vred=…rpm`.
* **Tuning order that matches how this loop was built:** set the per-wheel motor map first
  (drift is a calibration problem, not a gain problem) → `KP` per speed mode (linear in
  speed) → `TD`/`N` for damping → `FF_SCALE` for corners → `TI` / `TI_DEADBAND` last, only
  to null a residual standing bias → `V_RED_COEF` / `SR_CAP` if the AGV needs to slow
  itself through corrections.
* **All tuning is JSON.** Changing gains, speeds, sensor limits, or feedforward is a
  profile edit plus a restart; no Python change is needed.
