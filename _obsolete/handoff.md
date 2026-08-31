# AGV line-following controller — handoff

**Last updated:** 2026-08-31
**Status:** Working on the floor at 2000 r/min. Closed-loop line following is live.

CANopen control software for a 150 kg differential-drive AGV following magnetic
tape. Flask web UI, two Oriental Motor BLV-R drivers on CiA 402 pv mode, a SICK
MLS magnetic line sensor. Runs as a systemd service.

---

## ⚠️ Read this first

**The repository has zero commits.** `git ls-files` shows 29 tracked files, all
of them manuals and stale `.pyc` files staged as deleted. Every source file in
this project is **untracked**. One `rm` and the whole thing is gone — this has
already happened once and was only recovered by replaying a session transcript.

```bash
git add -A && git commit -m "AGV controller: line-following PID, web UI, profile"
```

Do that before anything else.

---

## Current state

| | |
|---|---|
| Cruise speed | **1600 r/min** (0.50 m/s) — has run clean at 2000 |
| Gains | `K_RATIO 11.3`, `KD 0.94`, `KI 0`, ζ = 0.294 |
| Driver ramp (6083h/6084h) | auto 2000 / 3000, manual 400 / 800 |
| Software ramp | 1000 r/min/s, jerk 4000 |
| `dry_run` | **false** — motors live |
| `invert_error` | **true** — established empirically, do not flip casually |
| Tests | 99 checks, all passing (`python3 test_autopilot.py`) |

### Measured performance (real runs, straight tape)

| run | speed | error RMS | range | lost track | saturation |
|---|---|---|---|---|---|
| `auto_20260831_093244` | 800 | 4.97 mm | −18 … +10 | 0 | none |
| `auto_20260831_102222` | 1500 | 2.34 mm | −5 … +3 | 0 | none |
| `auto_20260831_102448` | **2000** | **2.93 mm** | −8 … +5 | 0 | none |

Loop timing is healthy throughout: mean 20.3 ms, max ~30 ms at 50 Hz.

**This confirms the core design claim.** `Kp = K_RATIO · v` makes damping
speed-invariant, so the same gains hold from 800 to 2000 r/min — and they do.
Tracking got *better* with speed, not worse. No re-tune was needed at any step.

---

## Layout

```
agv-profile.json     ← every tunable parameter. Edit this, restart the service.
config.py            ← loads + validates the profile. Everything imports this.

app.py               Flask routes. Entry point.
canworker.py         Bus thread: NMT, SDO, 50 Hz control loop, arm/disarm.
autopilot.py         LineFollower — the PID. Pure computation, no I/O.
kinematics.py        body <-> wheels conversion. No control logic.
motion.py            Manual jog pad table and key bindings.
events.py            Operator event ring buffer (200). Survives a page reload.
runlog.py            Per-run CSV + PNG into logs/auto_<timestamp>/
plotrun.py           Per-run PNG. matplotlib, imported LAZILY (see Dependencies).
test_autopilot.py    65 offline checks. No hardware needed.

templates/  static/  Web UI. base.html is the shared shell.
debug_commands/      Standalone hardware tools. Do not make these import config.
manuals/ opman*/     Driver and sensor documentation, searchable.
draft_pid_design.md  Original design brief.
pid-other-agv.md     KIM2A reference implementation (different actuation, same geometry).
```

**Dependency graph:** `config` imports only stdlib; everything else imports
`config`. No cycles.

---

## Tuning

All parameters live in `agv-profile.json`. **`config.py`'s docstring is the
manual** — it carries a TUNING NOTES section explaining every non-obvious
setting, because JSON cannot hold comments. Read it before editing.

The loader is deliberately strict: unknown keys, missing keys, and wrong types
are all fatal at boot with the failing check named. A typo'd `"k_rato"` would
otherwise leave a gain at a value nobody chose.

```bash
# after any profile edit
sudo systemctl restart agv_controller
journalctl -u agv_controller -n 30    # a bad profile names its own failure here
```

Note the service has `Restart=on-failure`, so a bad profile shows up as a
5-second restart loop rather than a dead unit.

---

## Dependencies

Standard library only, **except matplotlib** for the per-run plot.

It is a `pip3 install --user` under `gvipc-evo-01`, living in
`~/.local/lib/python3.10/site-packages`. The systemd unit runs as that same user
with `HOME=/home/gvipc-evo-01`, so the import resolves — verified. **If the
service is ever moved to another user, the plot silently stops appearing** (the
CSV is unaffected; the failure is caught and recorded in `RunLog.error`).

`plotrun` imports matplotlib **lazily**, inside the render call, so the control
process never pays its ~1 s import or ~100 MB RSS. A test asserts this.
The first plot after a restart may take a few extra seconds while matplotlib
builds its font cache in `~/.cache/matplotlib`; that happens on the render
thread, after the CSV is already on disk.

## Open items

### 1. Curve capability is untested and is the real limit

Straight-line tracking is excellent, but **no curve has been run.** Steady-state
error on a curve is `1/(R · K_RATIO)`, independent of speed *and* of lookahead:

| tape radius | error at K=11.3 | at K=25 |
|---|---|---|
| 1.0 m | 88 mm | 40 mm |
| 1.5 m | 59 mm | 27 mm |
| 2.0 m | 44 mm | 20 mm |

The sensor window is ±100 mm, and the curve-entry transient runs ~1.4× the
steady value. **At the current gains the tightest usable radius is ~1.55 m.**
Raising `k_ratio` to 25 buys 0.65 m. Measure the tightest radius on the actual
track before assuming this is fine.

### 2. Sensor lookahead — decided: stay at 100 mm

400 mm was evaluated and rejected. It nearly triples damping (ζ 0.29 → 0.69) but
the sensor then reads `κ·Ls²/2` — 80 mm on a 1 m curve — *even when tracking
perfectly*, eating 80% of the window. That puts a hard floor of ~1.3 m on curve
radius that **no gain can lift**. At 100 mm, gain still buys tighter curves.

### 3. Deferred

- MEXE02 load inertia is still `0: Small (2×)`; should be `1: Medium (7.5×)`.
- `KI` is 0. Add only if a standing offset appears through curves.
- RPDO1 migration for `60FFh` (currently a blocking SDO write per tick).
- Curvature feedforward; `6072h` torque limit + traction breakaway measurement.
- Telemetry is 5 Hz vs a 50 Hz loop, so the *actual* wheel traces in run plots
  are 10× coarser than the commanded ones — they are drawn as steps, which is
  honest about the sampling. `timing.telemetry_period_s = 0.10` would halve that
  for ~10% of loop budget.
- `.gitignore` + first commit. Still nothing is committed (see the top).
- `debug_commands/` holds the whole bus layer that `canworker` imports; a rename
  to `canbus/` would stop the control path depending on a scratch directory.

---

## Gotchas

**Dry run does not free the motors.** CiA 402 "Operation enabled" *excites* the
motor and the velocity loop then holds zero — a servo lock, not a free shaft.
A non-excited brake motor has the brake clamped. Only the `FREE` input releases
it. `dry_run` therefore leaves the drivers de-energised entirely and never arms
them. Check the error sign by sliding a magnet under a **stationary** AGV.

**Never do bus I/O while holding `Controller._lock`.** `sdo_read()` drains RX
through `TpdoTap`, which calls `_on_pdo()`, which takes the same lock. This
shipped once and presented as 409s on arm *and* disarm with `/api/state`
hanging. `test_autopilot.py` has a source scan that fails the build if any
`self._read`/`_write`/`_nmt`/`bus.` call appears inside a `with self._lock:`
block. Keep it.

**`6083h` does two jobs.** It limits the forward ramp *and* the rate the wheel
difference can slew — which is the real ceiling on steering gain. Raising
`k_ratio` without raising it diverges; raising it without re-checking traction
is a different mistake. Neither the design brief nor the KIM2A reference notes
this coupling.

**The software ramp must stay below `6083h`** or the driver becomes the limiter
and the S-curve is lost. `config._validate()` enforces this.

**Don't make `debug_commands/` import `config`.** Those are standalone hardware
tools that must run on their own. `open_bus(bitrate=None)` defaults to the
module's own constant; `canworker` passes `config.CAN_BITRATE`.

---

## Verify

```bash
python3 test_autopilot.py          # 65 checks, no hardware
python3 -c "import app"            # exits 1 with a named check on a bad profile
sudo systemctl restart agv_controller
```

Then in the browser: `/manual` → ARM → the tape strip should populate and track
a magnet moved under the sensor. `/auto` → ARM → START → STOP, and confirm a new
`logs/auto_<timestamp>/` appears containing both `run.csv` and `run.png`.

The UI is one fixed non-scrolling page: telemetry rail on the left, content on
the right. Below 820 px wide it stacks and scrolls instead.
