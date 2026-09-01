# gvievo-01 structural refactor — canbus, health protocol, profiles

## Context

A delta analysis against the sibling `agv-kim2a-controller/` repo found that the two
codebases hold complementary, non-overlapping knowledge. KIM2A knows *what modules a
deployed AGV needs*; gvievo-01 knows *how to make a control loop provably correct*
(validating loader, 126 offline checks, invariants documented with the bug that
motivated them).

Three structural gaps in gvievo-01 are worth closing now, before the next sensor or the
second vehicle arrives, because each gets materially more expensive later:

1. **`debug_commands/` is the entire CAN bus layer**, not a scratch directory.
   `canworker` imports `open_bus`, `sdo_read`, `sdo_write`, `decode_state` and
   `decode_tpdo1` from it. The name actively misleads, and it invites someone to delete
   or reorganise a directory the running system depends on. (KIM2A has the identical
   defect — `modes.py` imports `RunRecorder` from `_debugging/plotter.py` — so this is
   drift both projects fell into independently, not a gvievo quirk.)

2. **There is no hardware-health contract, and driver staleness is undetected.**
   `_poll_telemetry()` keeps the last statusword forever when `_read()` returns `None`,
   so a driver that stops answering SDO **looks healthy indefinitely**. Meanwhile the
   MLS, the drivers and the RFID link each have their own bespoke liveness mechanism
   (`_sensor_last`, `_fault_seen`, `RfidLink._comms_ok`), and adding a lidar means
   editing `canworker`. KIM2A solved this with a driver health protocol plus a
   declarative two-tier watchdog table; that design is worth adopting, adapted to
   gvievo's threading model.

3. **`profiles/` is half-present.** The JSON already carries `profile_name`, and
   `config.load()` already takes a path, but there is no way to select a profile — the
   path is hardcoded. Two vehicle-specific facts (`CHANNEL`, `ADAPTER_SERIAL`) are also
   still hardcoded in `canbus/verify_drivers.py`.

**Intended outcome:** the bus layer is named for what it is; hardware health is one
declarative table with a two-tier fault policy that closes the silent-driver hole; and a
second vehicle is a new JSON file rather than a code change. Behaviour on the current
vehicle is unchanged except for the new critical-fault stop.

### Explicitly out of scope

- **Live/runtime tuning.** `systemctl restart` after a profile edit remains the
  supported workflow. KIM2A's `TuningState` dashboard writes are not being adopted.
- **The station/route layer** (KIM2A's `sequence_engine` + `mapping_store`). RFID stays
  read-only. The health protocol is a prerequisite for that work anyway, so this
  sequences correctly.
- **Layered directory restructure** (`core/`, `drivers/`, `app/`). Decision: stay flat
  for now. A separate planning doc will cover the layered move, to be written and
  executed **while connected to real hardware**, so any import or wiring fault surfaces
  against a live bus rather than in isolation.

---

## Item 1 — Rename `debug_commands/` to `canbus/`

Mechanical, no behaviour change. Do this first: it is trivially verifiable and unblocks
honest naming in the other two items.

**Move:** `git mv debug_commands canbus` (preserves history; the directory is tracked).

**First, untrack the stale bytecode.** `debug_commands/__pycache__/` still holds four
tracked `.cpython-310.pyc` files — the earlier cleanup commit caught only the root
`__pycache__`. `.gitignore` now covers the pattern, but already-tracked files stay
tracked, so `git mv` would carry them into `canbus/`. Run
`git rm -r --cached debug_commands/__pycache__` before the move.

**Keep it a plain directory on `sys.path`, not a package — do not add `__init__.py`.**
Each module inserts its own dirname and imports its siblings by bare name
(`from verify_drivers import ...` in `bus_health.py`, `drive_forward.py`, `read_mls.py`,
`verify_bus.py`). Converting to a package would create two module identities
(`verify_drivers` and `canbus.verify_drivers`) depending on entry point, with `open_bus`
defined twice. The flat layout also preserves the stated invariant that these stay
runnable standalone on a bench.

**Edits:**

- `canworker.py:28-31` — the `sys.path.insert(..., "debug_commands")` line and the
  comment block above it. Reword the comment: the directory is now named for its role,
  so the note becomes "these are the bus layer" rather than "despite the directory name".
- `canbus/run_web.py:16` — comment references `debug_commands/`. This file is a
  backwards-compat shim for an entry point that moved to `app.py`; consider deleting it
  instead (it is cruft of exactly the kind flagged in both repos). **Recommend delete**,
  but keep if any operator notes or scripts still call it.
- `README.md` — three references: the layout block (line ~102), the `TpdoTap` paragraph
  (~126), and the invariant heading (~368).

**Note:** `canbus/` goes on `sys.path[0]`, so its module names shadow same-named
installed modules. Current names (`verify_drivers`, `verify_bus`, `bus_health`,
`drive_forward`, `read_mls`) collide with nothing; keep it that way when adding files.

---

## Item 2 — Hardware health protocol + two-tier watchdog

The highest-value item. New module **`health.py`**, pure computation — no CAN, no Flask,
no file I/O, stdlib only. Same dependency-free stance as `events.py`, same "pure
arithmetic on the bus thread" stance as `_LoopHealth` in `canworker.py:95`.

### Why not copy KIM2A's driver ABC literally

KIM2A's `SensorDriver` assumes each driver is an async task owning its own I/O. In
gvievo the MLS and the two drivers **do not own their I/O** — the single bus thread does,
deliberately, because an SDO transfer is a send/recv pair that must not interleave. So
adopt the *health contract and the watchdog table*, not the *task-per-driver* part.
Copying KIM2A wholesale here would break gvievo's most important structural invariant.

### Design

Two source kinds, because the data arrives two different ways:

- **Push source** — the bus thread calls `mark_rx()` on every successful read. Used for
  the MLS (from `_on_pdo`) and each driver node (from `_poll_telemetry`). Written and
  read on the same thread, so no lock of its own.
- **Pull source** — wraps an existing snapshot callable, evaluated on demand. Used for
  the RFID link, which runs on its own thread and already exposes
  `RfidLink.snapshot()` with `comms_ok` / `carrier` / `rx_age_s`. Reusing it avoids
  cross-thread writes and a second lock entirely.

```
HealthSource(name, critical=False)
    mark_rx(now)      -> bump last_rx, set ok
    health(now)       -> {"ok", "last_rx", "age_s", "detail", "critical"}

PullSource(name, snapshot_fn, critical=False)   # same health() shape

HealthMonitor(table)          # table = [(source, timeout_s), ...]
    evaluate(now) -> {"system_error":  bool, "system_detail":  str,
                      "sensor_error":  bool, "sensor_detail":  str,
                      "sources":       {name: health_dict},
                      "changed":       [(name, up|down), ...]}
```

`HealthMonitor` holds the previous tier states internally and returns `changed` so the
caller emits **once per edge**. This is a hard requirement: `evaluate()` runs at 50 Hz,
and `events.py`'s docstring records that one chatty call site empties the 200-entry ring
in about four seconds. Centralising edge detection here also replaces the ad-hoc
`_fault_seen` dict rather than adding a third pattern beside it.

### Registration table (in `canworker.Controller.__init__`)

| source | fed by | timeout | tier |
|---|---|---|---|
| `mls` | `_on_pdo()` | `SENSOR_TIMEOUT_S` (0.1 s) | auto-only |
| `driver:1`, `driver:2` | `_poll_telemetry()`, on a successful `_read` | **new** `driver_timeout_s` | **critical** |
| `rfid` | `PullSource(self._rfid.snapshot)` | existing RFID timings | auto-only, registered only when `RFID_ENABLED` |

### Two-tier policy

- **critical** (a driver has gone silent) → same treatment as a watchdog trip:
  `_end_auto_run(reason, hard=True)`, zero the setpoint, set `_last_stop_reason`, emit
  `events.error` once on the edge. `_do_arm()` refuses while set.
- **auto-only** (MLS or RFID stale) → block an auto arm and auto START; manual keeps
  working, minus the tape strip. This **formalises the behaviour `_start_sensor()` and
  `SENSOR_SILENT_MSG` already implement** as an if-statement in `_do_arm`; it is not a
  new policy, it becomes a declared property of the source.

### Constraints the implementation must respect

- `evaluate()` does **no bus I/O** and is never called inside `with self._lock:`. The
  existing source scan in `test_autopilot.py` fails the build on violations — extend it
  to cover the new call sites rather than working around it.
- Emit on edges only, never per tick.
- **The browser watchdog (`_deadline`, `MANUAL_WATCHDOG_S` / `AUTO_WATCHDOG_S`) is a
  different mechanism and stays separate.** That is operator liveness; this is hardware
  health. Do not merge them, and say so in the docstring.

### Profile and config changes

- New key `timing.driver_timeout_s`.
- New validation in `config._validate()`: `driver_timeout_s > telemetry_period_s`, else
  a normal poll gap reads as a fault. This is the same class of cross-cutting check as
  the existing `telemetry_period_s >= loop_period_s` pairing — the kind neither module
  could make alone, which is why it belongs in the loader.

### Surfacing

Add `"health": {...}` to `Controller.snapshot()`. Keep the UI change small: surface a
critical fault on the existing `#link` pill and the states rail in `static/common.js`.
A dedicated health panel is optional and can follow.

---

## Item 3 — `profiles/` + `AGV_PROFILE` selection

**Move:** `git mv agv-profile.json profiles/agv-01.json` — `profile_name` is already
`"agv-01"`, so the file names itself correctly.

**`config.py`:**

```python
PROFILE_DIR     = os.path.join(_dir, "profiles")
DEFAULT_PROFILE = "agv-01"

def profile_path(name=None):
    name = name or os.environ.get("AGV_PROFILE") or DEFAULT_PROFILE
    return os.path.join(PROFILE_DIR, f"{name}.json")
```

`load(path=None)` keeps its signature and gains this resolution. Env var only, per the
decision — no CLI flag. Named `AGV_PROFILE` rather than KIM2A's `AGV_ID` deliberately:
both repos may be worked on from the same shell, and a shared variable name would let a
`export` intended for one vehicle silently retarget the other.

**No fallback to the old root path.** A missing profile must fail hard, naming the env
var and the directory searched — consistent with the loader's existing contract that a
bad profile stops the process at import with the failing check named. A silent fallback
is exactly the backwards-compat cruft flagged in KIM2A's `config.py`.

**New validation:** `PROFILE_NAME` must match the filename stem. A profile copied to a
new vehicle and not renamed would otherwise report the wrong identity in the event log
and in every run CSV header — silent, and only discovered when comparing runs later.

**Vehicle-specific bus facts:** `canbus/verify_drivers.py` hardcodes `CHANNEL = "can0"`
and `ADAPTER_SERIAL = "2087327F5548"` — per-vehicle hardware identity living in code, in
a repo whose point is now running several vehicles from `profiles/`. Extend `open_bus()`
to take `channel` and `adapter_serial` alongside the `bitrate` parameter it already has,
each defaulting to the module constant, and have `canworker` pass values from config.
This preserves the invariant that `canbus/` never imports `config`, using the pattern
`open_bus(bitrate=None)` already establishes.

Add `can.channel` (string) and `can.adapter_serial` (string, `""` = accept any) to
`_SCHEMA`. Using `""` rather than `null` avoids adding nullable-type handling to
`_coerce()`.

**Also update:** `README.md` (layout, running, configuration sections) and the systemd
notes — the unit gains an `Environment=AGV_PROFILE=agv-01` line.

---

## Tests

All new checks go in `test_autopilot.py`, following the existing `check(...)` style.

**Health (`test_health()`):**
- a source is not-ok until its first `mark_rx()`
- goes stale after its timeout, recovers on the next `mark_rx()`
- critical vs auto-only route to `system_error` / `sensor_error` respectively
- `changed` fires **once** per edge across many `evaluate()` calls at tick rate — the
  `events.py` flooding trap, asserted directly
- a `PullSource` reflects a supplied snapshot dict, including the RFID disabled case
- source scan: `health.py` imports nothing outside the standard library

**Existing scans to extend:**
- the `with self._lock:` / bus-I/O scan, to cover the new `evaluate()` call sites

**Config:**
- `driver_timeout_s` below `telemetry_period_s` is refused
- profile resolution honours `AGV_PROFILE`
- a missing profile names the searched path and the env var
- `profile_name` not matching the filename stem is refused

---

## Verification

```bash
python3 test_autopilot.py                     # 126 existing + new checks
python3 -c "import app"                       # clean import
AGV_PROFILE=nope python3 -c "import app"      # must fail, naming path + env var
python3 canbus/verify_bus.py                  # bench scripts still standalone
python3 canbus/read_mls.py snapshot
git grep -n debug_commands                    # expect no hits outside history
```

On hardware, with the vehicle **on blocks**:

1. `/manual` → ARM → tape strip populates and tracks a magnet.
2. Unplug the MLS → auto arm is refused with the sensor message; manual still drives.
3. Pull the CAN cable mid-run → a critical fault event appears once, the setpoint zeroes,
   and `stop_reason` names the driver.
4. `/auto` → ARM → START → STOP → a new `logs/NNNN-auto_<timestamp>/` appears with both
   `run.csv` and `run.png`.

---

## Ordering and risk

Do the items in order; each is independently committable and revertible.

1. **Rename** — mechanical, verified by `git grep` and the test suite.
2. **Profiles** — config-only, no runtime behaviour change on the current vehicle.
3. **Health** — the only item that changes live behaviour.

**Commission item 3 carefully.** It introduces a stop path that did not exist: a spurious
driver timeout will now halt a run that previously continued on stale telemetry. Set
`driver_timeout_s` generously at first (≈3× `telemetry_period_s`, so ~0.6 s) and watch
the event log across several runs before tightening it. The 5 Hz telemetry poll shares
the bus with setpoint writes, so occasional late reads are expected and must not trip it.

---

## Deferred

- **Layered layout** (`core/`, `drivers/`, `app/`) — separate planning doc, to be written
  and executed while connected to real hardware so wiring faults surface against a live
  bus.
- **Station/route layer** — `sequence_engine` + `mapping_store` equivalents, once the
  RFID wire protocol is confirmed by packet capture. Build it data-driven behind the
  validating loader.
- **Live tuning** — not planned; `systemctl restart` is the accepted workflow.
