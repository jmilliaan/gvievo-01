# gvievo-01 — AGV line-following controller

CANopen control software for a 150 kg differential-drive AGV that follows
magnetic tape. Two Oriental Motor BLV-R drivers in CiA 402 Profile Velocity mode
and a SICK MLS magnetic line sensor share one 125 kbps `can0`. A Flask web UI
provides a manual jog pad and an automatic line-following mode.

> **Status: line-following is being retired.** The vehicle is migrating to
> lidar SLAM navigation — see [manuals/slam-generalized-plan/](manuals/slam-generalized-plan/),
> and read `hardware-reconciliation.md` there first: it records where this
> vehicle's actual hardware diverges from the generic plan, and it wins over
> the other two documents wherever they disagree.
>
> `core/autopilot.py` and `core/branch.py` retire with the tape, along with
> their tests and the `/auto` page. Everything else — the strict profile
> loader, the CAN write deny-list, the kinematics, the health table, the
> device drivers — is framework-agnostic and carries forward as libraries the
> ROS nodes import. Sections below describing the tape-following control law,
> curve capability and junction handling are the record of a working vehicle
> and are accurate as written; they document a feature on its way out.

| | |
|---|---|
| Cruise | 1200 r/min = **0.377 m/s** (slow zone 800 = 0.251; ceiling 4000 = 1.257 m/s) |
| Gains | `K_RATIO 11.3`, `KD 0.94`, `KI 0` → ζ = 0.294 |
| Control loop | 50 Hz, telemetry 5 Hz, sensor field 2 Hz |
| Nodes | 1 left driver, 2 right driver, 10 MLS sensor (TPDO1 `0x18A`) |
| `dry_run` | **false** — motors are live |
| Tests | 866 offline checks, all passing |

---

## ⚠️ Safety model

**This software moves a 150 kg vehicle and has no authentication.** Anyone who
can reach port 5000 can drive it. Keep it on a trusted network.

Four rules are built into the design. Understand them before changing anything.

**Nothing moves until `/api/arm`.** Arming runs a preflight — error register
clear, Remote bit set, no FAULT on either driver — and refuses if any check
fails.

**A manual direction is HELD, not latched.** The browser re-POSTs `/api/drive`
every ~100 ms while a button or key is down. Miss three in a row
(`manual_watchdog_s` = 0.4 s) and the bus thread zeros the setpoint. A closed
tab, a dropped Wi-Fi link and a released button are indistinguishable to the
AGV, which is the point.

**Auto is latched but still watchdogged.** The auto page's telemetry poll
doubles as its heartbeat (`auto_watchdog_s` = 1.5 s), so a dead page stops the
run. The heartbeat is **opt-in**: only a page that sets `window.CLAIM_HEARTBEAT`
polls `/api/state?hb=1` and refreshes the deadline. A read-only page such as
`/monitor` therefore cannot hold a run alive after the auto page is closed, and
a page that forgets the flag stops the run rather than extending it.

**`dry_run` does not free the motors.** CiA 402 "Operation enabled" *excites*
the motor and the velocity loop then holds zero — a servo lock, not a free
shaft; a non-excited brake motor has the brake clamped instead. Only the `FREE`
input releases it. `dry_run` therefore leaves the drivers **de-energised
entirely** and never arms them. Check the sign of the error by sliding a magnet
under a **stationary** AGV, never by pushing it.

---

## Running

```bash
python3 main.py                         # 0.0.0.0:5000 — /manual and /auto
python3 main.py --port 5001
python3 main.py --host 127.0.0.1
AGV_PROFILE=agv-02 python3 main.py      # a different vehicle
```

**Which vehicle** comes from the `AGV_PROFILE` environment variable, which names
a file in `profiles/`. Unset means `agv-01`. There is no CLI flag and no
fallback: a name with no matching file is fatal at boot and the error lists the
profiles that do exist.

In production this runs as the `agv_controller` systemd unit, which sends
SIGINT rather than SIGTERM so the `KeyboardInterrupt` path de-energises the
motors on the way out. The unit carries the vehicle identity:

```ini
ExecStart=/usr/bin/python3 /home/gvipc-evo-01/agv_can/main.py
Environment=AGV_PROFILE=agv-01
```

`main.py` is thin and sits at the repo root precisely so `ExecStart` names a path
that will not move again when the tree below it is reorganised.

`--debug` enables Flask autoreload and is **off by default**: a reload would
open `can0` twice and orphan an armed driver.

```bash
sudo systemctl restart agv_controller
journalctl -u agv_controller -n 30    # a bad profile names its own failure here
```

The unit has `Restart=on-failure`, so a bad profile presents as a 5-second
restart loop rather than a dead unit.

### Dependencies

Standard library, plus `flask`, `python-can`, and `matplotlib`.

`matplotlib` is used **only** for the per-run PNG and is imported **lazily**,
inside the render call — the control process never pays its ~1 s import or
~100 MB RSS, and a test asserts this. It is a `pip3 install --user`, so if the
service is moved to a different user the plot silently stops appearing. The CSV
is unaffected; the failure is captured in `RunLog.error`, never raised.

---

## Layout

```
main.py            Entry point. Thin: sets up sys.path, calls the server.
config.py          Loads and validates the profile. Everything imports this.
canworker.py       Bus thread: NMT, SDO, 50 Hz loop, arm/disarm, telemetry.

core/              No hardware, no Flask. Computation and record-keeping.
  autopilot.py       LineFollower — the PID.
  branch.py          Which track to follow at a diverter. The seal-in latch.
  kinematics.py      body <-> wheels. No control logic, no sensor knowledge.
  motion.py          Manual jog pad table, labels, key bindings.
  health.py          Hardware liveness: the two-tier watchdog table.
  panel.py           Operator panel: debounced edges over the DI image.
  lidarframe.py      nanoScan3 UDP telegram decode. Not a safety function.
  canmon.py          Drive monitoring: the round-robin SDO object table.
  events.py          Operator event ring buffer (200). Survives a reload.
  runlog.py          Per-run CSV + PNG into logs/NNNN-auto_<timestamp>/
  plotrun.py         Per-run PNG. matplotlib, imported lazily.

drivers/           Everything that talks to a device.
  rfid.py            Chafon CF821 station-tag reader. Own thread and socket.
  dio.py             16-in/16-out digital I/O over Modbus TCP. Own thread.
  lidar.py           nanoScan3 UDP stream. Own thread. Not a safety path.
  canbus/            CAN layer: SDO, bus discovery, CiA 402, MLS decode,
                     alarm tables, the write deny-list. Runtime dependency,
                     and standalone on a bench.

app/               The web tier.
  server.py          Flask routes.
  templates/         base.html is the shared shell.
  static/            app.css and the per-page scripts.

tests/             866 offline checks. run_all.py runs them. No hardware.
profiles/          One JSON per vehicle. Every tunable parameter lives here.
manuals/           Driver, sensor and RFID documentation, searchable.
logs/              One directory per auto run.
```

**Layers say what a module may touch.** `core/` reaches neither the bus nor the
browser, `drivers/` owns every device conversation, `app/` only serves. The three
files left at the root are the ones you open first: the profile loader everything
imports, the orchestrator that runs the vehicle, and the entry point.

**The layer directories go on `sys.path`; they are not packages.** Every module
imports its neighbours by bare name, which is what lets `drivers/canbus/` still
run standalone on a bench. The cost is that module *basenames* are one flat
namespace — two modules may never share a name, and none may shadow a stdlib
module. `tests/test_layout.py` enforces both, along with the filesystem anchors
that would otherwise follow a module into its new directory.

**Dependency graph:** `config` imports only the standard library; everything
else imports `config`. No cycles.

---

## How it works

### One thread owns the bus

Every CAN frame goes through `canworker.py`. Flask request handlers never touch
the bus — they either mutate a setpoint under a lock (cheap, non-blocking) or
push a slow action onto a queue and wait on a `Future`.

This is not stylistic. An SDO transfer is a send/recv **pair** that must not
interleave with another, and `sdo_read()` drains the RX queue before
transmitting — two threads doing SDO at once read each other's replies.

`TpdoTap` wraps the bus and routes every **unsolicited** frame — the MLS stream,
EMCY alarms, drive heartbeats — before the SDO helpers can discard them. That is
what lets `sdo_read`/`sdo_write` be reused verbatim from `drivers/canbus/` while the
pushed traffic still reaches its decoder. It is the only thing standing between
a pushed frame and the bin: both helpers keep only frames matching
`0x580+node` and drop the rest.

### The control law

```
omega_cmd  = -(Kp*e + Ki*integral + Kd*d_filt)     Kp = K_RATIO * v
v_cmd      = v_base - speed_reduction
(N_L, N_R) = body_to_wheels(v_cmd, omega_cmd), then joint saturation
```

`Kp` scales with `v` deliberately. For a sensor mounted `Ls` ahead of the axle
the error dynamics are `e_dot = v*theta + Ls*omega`; substituting
`Kp = K_RATIO*v` gives

```
zeta = (Kd + Ls*K_RATIO) / (2*sqrt(K_RATIO*(1 + Ls*Kd)))
```

with **no `v` in it**. Damping is the same at 800 r/min as at 2546, which is
what makes commissioning by working the speed up valid rather than a re-tune at
every step.

**This is confirmed on the vehicle.** Settled straight-line tracking, measured
from `logs/`, all at `K_RATIO 11.3 / KD 0.94`:

| run | r/min | m/s | RMS | range | loop avg / max |
|---|---|---|---|---|---|
| `0001-auto_20260831_095403` | 800 | 0.251 | 7.17 mm | −12 … +3 | 20.4 / 29.3 ms |
| `0003-auto_20260831_102222` | 1500 | 0.471 | 1.98 mm | −4 … +3 | 20.4 / 29.0 ms |
| `0004-auto_20260831_102448` | 2000 | 0.628 | 2.28 mm | −4 … +5 | 20.4 / 30.8 ms |
| `0005-auto_20260831_111800` | 2000 | 0.628 | 1.52 mm | −4 … +6 | 20.5 / 29.8 ms |
| `0007-auto_20260831_182323` | 1600 | 0.503 | 1.51 mm | −3 … +5 | 20.4 / 29.4 ms |

No re-tune was needed at any step, and tracking got *better* with speed. Loop
timing is healthy throughout against a 20 ms budget.

### Branching at a junction

The MLS reports up to three line centre points and always keeps the **main**
track on `LCP2`, putting a diverter's branch beside it as `LCP1` or `LCP3`
(sensor manual 8.4.1, table 17). Which of them the PID follows is decided by
`core/branch.py` from RFID station tags, held in a PLC seal-in latch transcribed
rung for rung from the drawn design:

```
Branch_right = (SetRight OR Branch_right) AND NOT ClearRight AND NOT Branch_left
Branch_left  = (SetLeft  OR Branch_left ) AND NOT ClearLeft  AND NOT Branch_right
```

Seal-in, explicit reset, mutual interlock. **The seal-in is the whole point.** A
tag read is a one-scan pulse — the tag is past the reader a tick later — so
without it the order would evaporate long before the junction arrived. The latch
is cleared only by an exit tag placed *after* the junction, so no input can
change while a diverter is actually in view; that is why this needs no second
"commit" latch to hold the choice steady mid-junction.

The pulse is a rise in `tags_seen`, **not** the `tag` field. `tag` is held live
for `rfid.tag_hold_s` so a 5 Hz UI poll cannot miss one, and a held tag would
re-trigger its rung on every tick — harmless on a set contact, but it would pin
the latch off on a clear one. The ladder is scanned on the *sensor's* clock,
after the "no new TPDO1" early return, so a read is at worst deferred by one
10 ms frame.

Track selection needs **no case analysis on `#LCP`**: an order takes the extreme
position on the wanted side, so asking for a side that is not there yields
`LCP2`, the straight-through track. The safe answer falls out rather than being
special-cased — and it is not silent: `unhonoured` is set, and an event logged,
when a real diverter was in view and the ordered side was not one of its tracks.
A `#LCP 7` crossing is not a diverter and ignores intent entirely, following the
manual's own advice to navigate intersections by markers.

Disarm resets the latch. An order that survived a manual intervention would take
a junction on an intent given before whatever made the operator stop the
vehicle.

### Guards on the tick

| guard | behaviour |
|---|---|
| `sensor_max_mm` 100 | a reading beyond the sensor's range is **discarded** |
| `sensor_max_step_mm` 40 | a jump larger than this is **clamped** toward the last accepted |
| `sensor_timeout_s` 0.1 | no TPDO1 → `sensor_lost` → hold straight and stop |
| `line_loss_grace_m` 0.075 | tape gap budgeted as **distance**; 1.49 s standstill backstop (derived from the *slowest* cruise, `auto_slow_rpm`) |
| `ti_deadband_mm` 20 | conditional integration — integrate only inside, freeze outside |
| dt clamp | measured dt clamped to 0.004 … 0.1 s so a scheduling hiccup cannot blow up I and D |

`line_loss_grace_m` is a distance, not a time, because how far the AGV travels
on a stale correction is the thing that matters — and a distance rescales itself
with speed, even within a run as the ramp changes.

A stale sensor and a tape gap are **different failures**. No TPDO1 at all means
comms are gone and the AGV no longer knows where the line is, so it holds
straight and stops immediately. A valid frame with no track is a gap, and is
bridged on the last good correction until the distance budget is spent.

### Saturation and the inner wheel

The inner-wheel floor is enforced by limiting the **differential**, not by
clipping one wheel — clipping one alters the effective turn ratio. The ceiling
scales **both** wheels by the same factor, so the commanded arc is preserved.

### Hardware health

Separate from the browser watchdogs above, and deliberately so: those cover an
absent **operator**, this covers an absent **device**. [core/health.py](core/health.py)
holds one table, one row per supervised device, and each row declares its own
tier:

| device | fed by | timeout | losing it stops |
|---|---|---|---|
| `driver:1`, `driver:2` | a telemetry read that answered | `driver_timeout_s` 0.6 s | **everything** |
| `mls` | a decoded TPDO1 frame | `sensor_timeout_s` 0.1 s | auto only |
| `rfid` | the link's own `snapshot()` | `silent_warn_s` | auto only |

Losing a driver means the wheels can be neither commanded nor observed, so every
mode stops and an arm is refused. Losing the MLS or the reader means the tape or
the stations are unknown — auto stops, manual keeps working, because manual
never needed them.

A source that has **never** answered is not a fault: the drivers are silent
until the bus is up and the sensor until it is NMT-started, and reporting that at
boot would cry wolf before anything is connected. Only a device that answered
once and then stopped counts as lost.

This closes a real hole. `_poll_telemetry()` keeps the last statusword when an
SDO read returns `None`, so before this a driver that stopped answering looked
healthy for as long as the process ran.

### Drive monitoring

**Diagnostic only — not a safety path.** The safety chain is
lidar/encoders → FX3 → HWTO1/HWTO2 → STO, wired in hardware with EDM returned to
the FX3. Nothing read over CAN is rated, redundant or certified, and nothing
here may decide whether it is safe to move. See
[manuals/can-monitoring-plan.txt](manuals/can-monitoring-plan.txt).

`/monitor` shows both drives side by side, so a left/right divergence is visible
at a glance. Three channels feed it:

| channel | how | what |
|---|---|---|
| **EMCY** | pushed on `0x080+n` | alarms, decoded by name and severity |
| **heartbeat** | pushed on `0x700+n` | liveness and NMT state |
| **analogue** | SDO, round-robin | voltage, current, temperature, load, deviation |

**Pushed frames are routed by `TpdoTap`, and that is not optional.** Both SDO
helpers open by draining the RX queue and then keep only frames matching
`0x580+node`, discarding the rest — so any frame class not routed by the tap is
silently lost for as long as a transfer is in flight, which is most of the time.

**The analogue objects are polled one per node, round-robin, every 0.1 s.** At
tick rate that would be two SDO round-trips out of every 20 ms budget — ~4 ms of
tick and a fifth of the bus — for values that move on a thermal timescale.
Paced, it costs ~0.8 ms of average tick and ~4 % of a 125 kbps bus, sweeping all
eleven objects in about a second. A late tick is a steering update the vehicle
does not get, and that matters more than sampling a temperature faster.

Data types come from the manual, not the monitoring plan: the plan guesses
`40A4h` and `40A3h` as INT32 when both are **INT16**, and a 16-bit signed value
read as 32-bit is plausible-looking garbage rather than an error. Statusword
bit 5 (QS) is likewise **active-low** — `decode_state()` already reports quick
stop correctly, so it is deliberately not exposed as a flag.

Tier 1 (`403Fh`: EDM-MON, HWTOIN-MON, ETO-MON, MBC) is **not implemented**. It
needs the drives reconfigured through MEXE02 and the bit positions verified on
the bench first.

### What the vehicle may write over CAN

CANopen is bidirectional, and several objects can defeat safety behaviour from a
single stray frame. [drivers/canbus/guard.py](drivers/canbus/guard.py) enforces a deny-list on
every write path, and `/monitor` publishes it:

| | |
|---|---|
| **permitted** | `6040h` controlword, `6060h` modes, `6083h`/`6084h` ramps, `60FFh` target velocity, `1017h` heartbeat |
| **refused** | `403Eh` (bit 6 is **FREE** — releases the holding brake on *both* drive wheels), `40D0h` clear ETO, `40C0h` alarm reset, `6040h` bit 7 fault reset, `1010h`/`1011h` store/restore, `40C6h` and all `4xxxh` parameters |

A denied write raises rather than being silently dropped: a command a caller
believed had landed is its own hazard. Clearing ETO or resetting an alarm
automatically would be an automatic restart, which ISO 3691-4 prohibits.

---

## Configuration

Everything tunable lives in `profiles/<name>.json`, selected by `AGV_PROFILE`.
**`config.py`'s docstring is the manual** — it carries a TUNING NOTES section
explaining every non-obvious setting, because JSON cannot hold comments. Read it
before editing.

The loader is deliberately strict, and this is the main thing the JSON buys over
Python constants:

1. **Unknown and missing keys are both fatal.** A typo'd `"k_rato"` would
   otherwise leave the gain at whatever the code last defaulted to, and the
   vehicle would drive off with a number nobody chose.
2. **Only primitives are stored.** Anything derivable is derived, so the file
   cannot hold a geometry that contradicts itself.
3. **Validation runs before anything is published.** `load()` parses and
   validates into a fresh namespace and publishes only on success, so nothing
   ever observes a half-applied profile.
4. **`profile_name` must match the filename.** A profile copied for a second
   vehicle and not renamed would report the old identity in the event log and in
   every run CSV header — silent, and only noticed when comparing runs later.

Cross-cutting checks that neither module could make alone are enforced here —
for example `autopilot.ramp_accel_rpm_s` **must** stay below
`drivers.ramp.auto.accel`, or the driver becomes the limiter and the software
S-curve is lost, and `timing.driver_timeout_s` **must** exceed
`telemetry_period_s`, or the gap between two normal polls reads as a dead driver.

**Junctions are data, not code.** `branch_latch` is the one list in the profile —
one row per junction, `{"entry_tag", "exit_tag", "branch"}` — and it has its own
reader rather than a `_SCHEMA` entry, so adding a junction stays a profile edit
and never a code change. Every check in that reader exists to stop a rung being
silently **dead**, which is the only failure mode this table has: a tag that
never matches produces no error, no log line and no motion — the AGV simply
drives past its junction. So ids must be hex text exactly as `rfid.tag_of()`
emits them (`"0002"`, never `2`, which could never match), an entry and its exit
may not be the same tag, no tag may mean two things, and none may also sit in
`rfid.ignore_tags` where it would be discarded before the ladder saw it. The one
thing the loader cannot check is whether an id is what the reader actually sends
— jog over each tag and confirm the station tile names it.

Derived from the profile, never stored:

```
MPS_PER_RPM         3.1416e-4      RAD_S_PER_RPM_DIFF     6.4642e-4
RPM_PER_MPS         3183.1         MAX_SPEED_MPS          1.2566
MANUAL_HALF_RPM     720            LINE_LOSS_GRACE_MAX_S  1.492
DT band             0.004 .. 0.1   TPDO1_COB              0x18A
```

The two modes want opposite things from the drivers, so `6083h`/`6084h` are
written per mode at arm time. Manual is set gentle — the driver does all the
shaping for a hand-jogged pad, and decel stays faster than accel because
releasing the button is the safety-relevant direction. Auto is set as
transparent as is safe, because the software S-curve shapes the motion instead.

---

## Curve capability

**No curve has been driven yet.** The numbers below are from a
constant-curvature simulation against the real `LineFollower`, including the
1 mm sensor quantisation, the 50 Hz tick, the 20 ms transport delay and the
`6083h` wheel slew limit.

Steady-state error on a curve is **not** `1/(R·K_RATIO)`. The speed reduction
changes it, because `Kp` is computed from the *unreduced* ramp speed
(`autopilot.py`, `v_now = rpm_to_mps(self._v_rpm)`) while the wheels receive
`v_base - red`. Shedding speed is therefore an effective gain multiplier of
`1/(1-f)`, and the steady state solves to

```
e_ss = e0 / (1 + sr_pos_frac * e0)        e0 = 1000/(R*K_RATIO) mm
e_ss = e0 * (1 - sr_cap)                  once the reduction saturates
```

Simulated at the shipping profile — the closed form agrees within ~1 mm:

| radius | e_ss | **peak (curve entry)** | speed through curve |
|---|---|---|---|
| 1.5 m | 41 mm | 53 mm | 0.344 m/s (68%) |
| 1.0 m | 53 mm | 72 mm | 0.301 m/s (60%) |
| 0.8 m | 61 mm | 88 mm | 0.276 m/s (55%) |
| 0.7 m | — | **exceeds ±100 mm → line lost** | — |

**The binding constraint is the entry transient against the ±100 mm sensor
window, not the steady-state error.** Beyond the window `_read_error` discards
the frame as implausible, the grace budget drains, and the run stops on
`line_lost`. **Tightest usable radius at the current profile is ~0.8 m.**

To go tighter without touching `auto_rpm` or the sensor lookahead:

- **`sr_cap` 0.45 → 0.65 reaches ~0.6 m.** This is the knob that matters,
  because at tight radii the reduction is already pinned at the cap — raising
  `sr_pos_frac` or `sr_rate_frac` alone changes **nothing** below ~0.8 m until
  the cap is lifted.
- **`k_ratio` 11.3 → 18 with `kd` 0.94 → 2.2 reaches ~0.5 m**, improves ζ to
  0.43, cuts straight-line overshoot (13.4 → 8.4 mm) and settling (6.5 → 3.6 s),
  and is *faster* through curves (70% of base at R = 1.0, vs 60%) since less
  error means less speed reduction. Simulated stable at the existing `6083h` =
  2000 up to 2546 r/min.

Increasing `ki` is **not** the first move: `ti_deadband_mm` is 20 mm and curve
error is 40–70 mm, so the integrator is frozen exactly where it would help, and
widening the deadband inverts the anti-windup it exists to provide.

Curvature feedforward is the structurally correct fix — it drives `e_ss` to zero
at any gain — but it needs a curvature estimate and is a code change, not a
profile edit.

Note the lookahead trade before reaching for it: 400 mm was evaluated and
rejected. It nearly triples damping, but the sensor then reads `κ·Ls²/2` — 80 mm
on a 1 m curve — *even when tracking perfectly*, which puts a hard floor on
curve radius that no gain can lift. At 100 mm, gain still buys tighter curves.

---

## Logs

Each START/STOP cycle produces `logs/NNNN-auto_YYYYmmdd_HHMMSS/` containing
`run.csv` and `run.png`, so a run is one self-contained thing to copy, attach or
delete. The header line records the full gain set, so a plot is never ambiguous
about which tune produced it.

`NNNN` is a zero-padded run number, derived at START from the highest prefix
already in `logs/` — there is no counter file to fall out of step with the
directory. It is the handle a human cites ("run 17"), it appears as the plot
title, and it makes two runs started in the same second distinct; under the
bare-timestamp scheme they collided and the second silently overwrote the
first. Archiving or deleting a run leaves a gap in the sequence rather than
causing the next run to reuse a name.

Rows are buffered and flushed about once a second — the control loop runs on the
bus thread, and a per-row write would put filesystem latency straight into the
50 Hz path. Logging continues for `log_tail_s` after a stop so the deceleration,
which happens entirely inside the drivers, lands in the CSV.

Plot axes are **fixed** from `plot.err_range_mm` / `plot.rpm_max` so two runs can
be compared by eye rather than each being scaled to its own data. Traces hard
clip at the frame.

Telemetry is 5 Hz against a 50 Hz loop, so the *actual* wheel traces are 10×
coarser than the commanded ones. They are drawn as steps, which is honest about
the sampling.

---

## Testing

```bash
python3 tests/run_all.py      # 866 checks, no hardware
python3 -c "import main"      # exits 1 with a named check on a bad profile
```

Two kinds of test: a plant simulation that integrates
`e_dot = v*theta + Ls*omega` against the real `LineFollower` including the
`6083h` slew limit, and behavioural assertions on the guards. A negative control
asserts the rig can actually *see* instability (`K_RATIO = 100` must diverge),
without which the passes would mean nothing.

The suite is split by subject under `tests/`, and `run_all.py` **pins both the
module list and the total check count**. Splitting the safety net has one silent
failure mode — a module that stops being imported costs coverage while the run
still ends in "all checks passed" — so a dropped module fails the run instead.
Raise `EXPECTED_CHECKS` deliberately when adding checks; never lower it to get a
green run.

It also contains **source scans** that fail the build on structural regressions:
any `self._read` / `_write` / `_nmt` / `bus.` call inside a `with self._lock:`
block, a module whose filesystem anchor followed it into a new directory, and a
basename collision on the flat `sys.path`. Keep them — see below.

After a hardware change: `/manual` → ARM → the tape strip should populate and
track a magnet moved under the sensor. `/auto` → ARM → START → STOP, and confirm
a new `logs/NNNN-auto_<timestamp>/` appears containing both `run.csv` and
`run.png`.

---

## Invariants

**Never do bus I/O while holding `Controller._lock`.** `sdo_read()` drains RX
through `TpdoTap`, which calls `_on_pdo()`, which takes the same lock. This
shipped once and presented as 409s on arm *and* disarm with `/api/state`
hanging. The lock is an `RLock` as a backstop; keeping bus I/O out of locked
sections is the actual fix, and the source scan enforces it.

**`6083h` does two jobs.** It limits the forward ramp *and* the rate at which
the wheel difference can slew, which caps yaw acceleration at
`2 * accel * RAD_S_PER_RPM_DIFF` = 2.59 rad/s² at the present 2000 (r/min)/s.
Raising `k_ratio` far without raising it diverges; raising it without
re-checking traction is a different mistake.

**Anything that must stay proportional to speed has to be *expressed* relative
to speed.** `sr_pos_frac` / `sr_rate_frac` are fractions of base speed and
`line_loss_grace_m` is a distance for exactly this reason — as absolutes they
silently lost authority when cruise went 800 → 2000 and nobody rescaled them.

**Only operator-relevant transitions may emit events.** At 50 Hz a single chatty
call site flushes the entire 200-entry ring within four seconds. Nothing on a
per-tick path emits, and anything edge-triggered (a driver fault, a lost tape)
fires once per **edge**, not once per poll.

**`drivers/canbus/` is a runtime dependency, not a scratch directory.** `canworker`
imports `open_bus`, `sdo_read`, `sdo_write`, `decode_state` and `decode_tpdo1`
from it. Moving or renaming that directory breaks the server. Do **not** make
those modules import `config` — they must stay runnable standalone on a bench;
where they need a vehicle-specific value, take it as a parameter defaulting to
the module constant, the way `open_bus()` already does.

It is also deliberately **not** a package. Its modules import each other by bare
name so they run standalone, and adding `__init__.py` would resolve them twice —
once as `verify_drivers`, once as `canbus.verify_drivers` — defining `open_bus`
in two places depending on the entry point.

**Wheel sign convention:** both drivers take a **positive** `60FFh` to travel
forward. If you swap a motor, re-flash a driver or remount a wheel, re-verify on
blocks and set `vehicle.invert_left` / `invert_right` rather than editing
`motion.py`'s table — the table stays in vehicle terms.

**`invert_error` is `true`**, established empirically on 2026-08-31: tape to the
right of the sensor reported −53 mm, tape to the left +20 mm. Do not flip it
casually. A wrong sign steers the AGV off the line and accelerates away from it.

**RFID silence is not a fault.** The reader pushes only when a tag is in the
field, so a quiet link is the normal state between stations. Health is
*connection* state, not data flow — which is only trustworthy because the socket
sets keepalive and `TCP_USER_TIMEOUT`, and because the link is built
point-to-point with no switch so a parted cable drops carrier in milliseconds.

---

## Known gaps

- **No curve has been driven.** The section above is simulation. Measure the
  tightest radius on the actual track before trusting any of it.
- **No junction has been driven.** `branch_latch` carries one left-hand junction
  (`0002` in, `0001` out) for the U-turn on the test track. The ladder and the
  track selection are covered by tests, but nothing has been run on the vehicle,
  and the two tag ids were read off the manual-jog display rather than a capture.
- **`config.py`'s `rfid.*` docstring is out of date.** The whole block is
  duplicated, it documents keys that are not in `_SCHEMA` (`inventory_cmd`,
  `epc_offset`, `handshake_hex`, `poll_period_s`, `comms_timeout_s`), it omits
  the ones that are, and it says `enabled` ships false while the profile has it
  true. The loader is strict enough that a typo is fatal at boot; its own
  documentation should not be the loose part.
- **`__pycache__` is tracked in git** — 11 `.cpython-310.pyc` files from the
  first commit. Run `git rm -r --cached __pycache__` alongside the `.gitignore`
  change.
- **`60FFh` is a blocking SDO write per tick.** RPDO1 migration would remove
  ~1.8 ms × 2 nodes from the 20 ms budget.
- **RFID wire protocol is inferred, not captured.** The framing is lifted from
  the same reader hardware on the KIM2A vehicle, and the init command's banner
  reply is consumed deliberately rather than mistaken for a tag, but none of it
  has been confirmed against a packet capture on this unit.
- MEXE02 load inertia is still `0: Small (2×)`; should be `1: Medium (7.5×)`.
- `KI` is 0. Add only if a standing offset appears.
- Deferred: curvature feedforward, `6072h` torque limit, traction breakaway
  measurement, and `timing.telemetry_period_s = 0.10` to halve the coarseness of
  the actual-speed traces for ~10% of loop budget.
