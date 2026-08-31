# AGV KIM2A Controller — Dossier

**Branch:** `tn-feature03` · **HEAD:** `9ead314` *pid fixes* · **Repo:** `jmilliaan/agv-kim2a-controller`

| Item | Value |
|---|---|
| Language / runtime | Python 3.11+, single `asyncio` event loop + 1 Flask daemon thread |
| Entry point | `main.py` (`AGV_ID=agv_tn python3 main.py`) |
| Source size | ~6.8 kLOC Python across 40 files (excl. captured CSV/PNG artifacts) |
| Deployment | systemd unit `agv-controller.service`, `Restart=always RestartSec=2` |
| Branch delta vs `main` | 279 files, +59.5k / −13.9k — full restructure into `core/`, `drivers/`, `profiles/`, `app/` |
| Profiles present | `agv1_kim`, `agv2_kim`, `agv_tn` (branch focus = AGV B "TN") |

---

## 1. What the AGV Is

The KIM2A is a differential-drive, magnetic-tape-following tow AGV built for in-plant trolley transport. Guidance comes from a Roboteq MGS1600 magnetic guide sensor reporting lateral offset in millimetres over CANopen (CANable2 USB, slcan, 500 kbps, COB-ID 390); the same sensor frame carries tape-detect and left/right marker flags used as positional triggers. Station identity comes from a separate RFID reader on a raw TCP socket. All electrical I/O runs over Modbus TCP to two remote I/O islands — a 16-DI/16-DO module for buttons, mode switch, E-stop, lidar zone contacts, impact bumper, motor direction/brake relays, horn and pusher, and a 2-channel AO module driving the motor-speed DACs (0–4095 → 0–10 V). Optional Mitsubishi FX5U handshake over SLMP/MC Protocol Type3E is present and gated by a feature flag (enabled on AGV A, disabled on AGV B). The vehicle carries a double-acting linear pusher for trolley engage/release, a two-tone horn, and a three-zone safety lidar mapped to plain DI: outer = indicator only, middle = force SLOW, inner = Category 1 protective stop; a bumper DI triggers the same Cat 1 path with a manual-clear-then-2 s hold.

Behaviourally the AGV is a state machine with two operator-facing modes and an automatic tape-follow behind them. In MANUAL a pendant (or the web jog page) maps button combinations to direct DO/AO motion primitives. In ARMED the vehicle sits ready; a START rising edge with tape present promotes it to RUNNING, where a PID loop closes lateral error against the tape at one of three speed setpoints (HIGH / SLOW / EXTRA_SLOW) with gain scheduling between HIGH and SLOW gain sets. Station behaviour is not hard-coded: an RFID tag or tape marker fires a declarative sequence (end cycle, start cycle, slow zone, timed pause, pause-until-tag, pulse pusher) defined in JSON and editable at runtime from the dashboard, with backup rotation and an audit log. AGV B differs from AGV A in three profile-level ways that matter for control: the guide sensor is mounted rear-facing (`sensor_orientation: -1`, which flips the PID error sign), the AO output is capped at 5.0 V rather than 10 V, and each wheel has its own independently fitted voltage→RPM calibration derived from encoder runs in `_calibration/` so the vehicle tracks straight open-loop. A Flask dashboard on port 5000 exposes live state, jogging, I/O monitor, runtime tuning, mapping editor and an event log; a `safety_watchdog` task independently zeroes the analog outputs on driver comms loss.

---

## 2. Code Structure, Architecture & Patterns

### 2.1 Layering

| Layer | Files | Responsibility |
|---|---|---|
| Entry / lifecycle | `main.py` | Driver instantiation (feature-gated), `asyncio.gather` of all tasks, signal handlers, `shutdown()` output zeroing, `request_restart()` for systemd bounce |
| Config | `config.py`, `profiles/*.json` | Module-import-time load of `profiles/{AGV_ID}.json`; every tunable is a module attribute |
| Shared state | `state.py` | `AMRState` — 5 domain dataclass-style objects + flat property shims + asyncio queues |
| Control / FSM | `modes.py` (942 L) | `mode_manager`, `auto_mode`, `manual_mode` |
| Control algorithm | `core/pid.py` | `PIDController` — filtered D, deadband I, output clamp, speed reduction |
| Behaviour | `core/sequence_engine.py`, `core/mapping_store.py` | JSON-declarative RFID/marker sequences; persistence, validation, compile/decompile, backup, audit |
| Actuation math | `motion.py` | Kinematics, per-wheel calibration, `_drive()` primitive, Cat 1 / Cat 2 stops, pusher |
| Hardware | `drivers/*.py` + `drivers/base.py` | One class per protocol, `SensorDriver` / `ActuatorDriver` ABCs |
| Auxiliary tasks | `safety_watchdog.py`, `rfid_processor.py`, `horn_controller.py` | Health monitor, tag dispatch, horn arbitration |
| UI | `app/app.py` (743 L) + 6 Jinja templates | Flask in a daemon thread, ~30 REST endpoints |
| Observability | `logger.py`, `_debugging/plotter.py` | Rotating file/console logging; auto-run recorder |
| Offline tooling | `calibration.py`, `check_encoder.py`, `_calibration/fit_voltage_rpm.py`, `_debugging/*` | Wheel-speed calibration rig, standalone hardware probes |

### 2.2 Runtime task graph

| Task | Type | Rate | Consumes → Produces |
|---|---|---|---|
| `DIReader.run` | Sensor | 50 ms | Modbus DI → `latest_di`, `di_queue` (applies `DI_FLIPPED`) |
| `CANReader.run` | Sensor | event | CAN frames → `latest_sensor`, `sensor_queue`, `can_last_rx` |
| `RFIDReader.run` | Sensor | event | TCP stream → `rfid_queue` (4-char hex tags) |
| `DOWriter.run` | Actuator | queue | `do_queue` → coil writes |
| `AOWriter.run` | Actuator | queue | `ao_queue` → register writes (`v/V_RANGE*DAC_RES`) |
| `SLMPDriver.run` | Actuator | 20 ms | `run_in_executor` sync PLC read/write cycle |
| `safety_watchdog` | Monitor | 50 ms | driver `get_health()` → `system_error` + immediate AO zero |
| `rfid_processor` | Dispatch | queue | `rfid_queue` → `engine.on_rfid_tag()` |
| `horn_controller` | Actuator | — | mode/fault state → horn DO |
| `mode_manager` | FSM | loop | Owns all transitions; spawns/cancels `auto_mode` or `manual_mode` as subtasks |
| Flask `run_server` | Thread | — | Reads state (GIL-safe), single-attribute writes back |

### 2.3 State machine

| From → To | Trigger |
|---|---|
| `None` → `manual` / `armed` | `DI_MODE_SWITCH` at startup (`MODE_SWITCH_INVERT` supported) |
| `armed` → `running` | `DI_START` rising edge + tape detected |
| `armed` → `reverse` | `reverse_auto_request` (Flask) + tape detected |
| `running`/`reverse` → `armed` | `DI_RESET` rising edge (or request cleared) |
| any → `emergency` | `DI_EMERGENCY` (NO contact, True = triggered) |
| `emergency` → `manual`/`armed` | `DI_RESET` rising edge + switch position |
| any ↔ `manual` | Live mode switch |

`auto_mode` is one coroutine serving both directions; `direction="reverse"` sets `error_sign=+1`, pins speed to SLOW, and disables sequence stops and RFID/marker hooks.

### 2.4 Recurring patterns

- **Profile-as-configuration.** No control constant is literal in code. `config.py` reads one JSON at import, with a 3× retry on filesystem lookup (slow SD/NFS at boot) and graceful fallback to legacy `parameters.json`. Backwards-compatible defaults are supplied via `.get()` for every key added after AGV A shipped (`ao_max_voltage`, `sensor_orientation`, `DI_BUMPER`, `pusher_channels`, `horn_channels`, `motor_cal`).
- **Keep-latest queue drain.** Every consumer drains its queue fully each cycle and keeps only the final frame, so a fast producer never builds a stale backlog into the control loop.
- **Driver ABC + health contract.** `SensorDriver._record_rx()` / `get_health() → {ok, last_rx, detail}` gives the watchdog a uniform interface. Actuators are deliberately not monitored. Watchdog entries carry an "auto-only" flag so a CAN or RFID loss degrades to manual rather than halting the vehicle outright.
- **Feature-flag gating at instantiation.** Drivers are constructed as `X() if config.X_ENABLED else None`, and task-list assembly is conditional — a disabled subsystem contributes no task and no watchdog entry.
- **Centralised reset closure.** `_reset_control_state(reason)` inside `auto_mode` is a `nonlocal` closure zeroing PID state, the accel ramp setpoint, the published telemetry dict, and forcing a gain recompute. Every safety branch (sequence stop, bumper, lidar, tape loss, CAN timeout and each of their recoveries) routes through it with a reason string. Per-site edge flags are explicitly *not* touched — the caller owns those.
- **Edge-tracked fault logging.** `tape_was_lost`, `can_timed_out`, `was_sequence_stopped` exist so a flapping condition emits one log line and one motion command per edge instead of per cycle.
- **Declarative behaviour.** `SequenceEngine` dispatches on JSON action types (`set_speed`, `wait_marker`, `stop_agv`, `resume`, `sequence_stop`, `wait_seconds`, `plc_request`, `wait_plc_complete`) with `register_action()` for extension. One sequence at a time via an `_active_sequence` guard, plus `requires_mode` and cooldown preconditions.
- **Override-never-mutate persistence.** `mapping_store` writes `profiles/{AGV_ID}_sequences.json` and never touches the profile. Saves rotate `.bak.1`…`.bak.5`, append to `*_sequences.audit.jsonl`, and set a reload-pending flag consumed on the next ARMED entry (with an "apply now" path rejected while a sequence runs). A corrupt override is renamed aside and surfaced to the dashboard Errors page.
- **Non-blocking discipline.** Sync hardware libraries (`pymcprotocol`) go through `run_in_executor`. Matplotlib is imported lazily and only after the CSV is on disk, so a broken plotting install cannot lose data.
- **Defensive accessors.** `_di_bit(di, idx, default)` tolerates `None` state, `None` channel index (profile without lidar/bumper) and short Modbus reads, so a partial read cannot kill `mode_manager` and leave a motion subtask orphaned.
- **Safety-category vocabulary in code.** `set_cat1_stop()` (decel then brake) vs `idle()` (Cat 2 hold, no mechanical brake) is applied per hazard: lidar/bumper get Cat 1, tape loss gets Cat 2.

### 2.5 Structural observations

| Observation | Impact |
|---|---|
| Production code imports from `_debugging.plotter` | Control path depends on a directory named as scratch; no `__init__.py` (works only via PEP 420 namespace packages) |
| `_obsolete/io_hardware.py`, `_obsolete/slmp_handler.py` retained | Dead duplicates of live driver logic — divergence risk if someone edits the wrong copy |
| `logs/temp_latest_log.txt` (1694 lines) committed | Runtime artifact in VCS; `.gitignore` covers `*.log` but not `.txt` |
| ~180 CSV/PNG run captures committed under `_motion_analysis/` and `_calibration/` | Repo bloat; these are generated outputs |
| `modes.py` at 942 lines | `auto_mode` alone carries emergency, sequence, bumper, lidar, tape, CAN, PID, telemetry, recorder and diagnostics concerns in one `while True` |
| Two independent plotting styles (`_debugging/plotter.py`, `calibration.py`) | No shared figure convention — different dpi, size and palette |

---

## 3. Auto-Run PID Plotting & Logging

### 3.1 Recording pipeline

| Stage | Location | Detail |
|---|---|---|
| Instantiate | `modes.auto_mode`, before the loop | `recorder = RunRecorder()` then `recorder.start()` — a fresh recorder per auto-mode entry |
| Sample | `modes.auto_mode`, inside `if sensor is not None` | `recorder.record(error_mm=dbg["e"], left_rpm, right_rpm, pid_output=dbg["output"], d_term=dbg["d"])` — five required kwargs |
| Flush | `modes.auto_mode` `finally:` | `recorder.stop()` → writes CSV, then PNG |

Consequences worth knowing:

- Recording is bound to the **auto_mode task lifetime**, not to a "run". Any `mode_manager` cancellation (RESET, mode switch, emergency, system error) ends the file; re-entry starts a new one.
- **Reverse runs are also recorded**, and the PNG title still reads "AGV Auto Run" with no direction field.
- `record()` sits inside the sensor-present branch, so the series is sampled at **sensor-frame arrival**, not at `DT`. Cycles where the queue was empty produce no sample — the CSV `time_s` column is therefore non-uniform and must be treated as irregularly sampled for any offline FFT/derivative work.
- Storage is six unbounded Python lists. At AGV B's 20 Hz that is ~72 k samples/hour; a full shift accumulates tens of MB of live heap with no cap or downsampling.
- `stop()` runs matplotlib **on the event loop**, inside a `finally` that often executes during task cancellation. A 14×6 in @ 150 dpi render blocks every other task (including `safety_watchdog`) for the duration.

### 3.2 Plotter configuration

| Constant | Value | Notes |
|---|---|---|
| `PLOTTING_ENABLED` | `True` (committed state) | Module-level flag; `start`/`record`/`stop` are all no-ops when `False`, and matplotlib is never imported |
| `PLOT_DIR` | `/home/amr-quality/traknus/agv-kim2a-controller/_motion_analysis` | **Hardcoded absolute path** including a specific username — does not resolve on other AGVs; also contradicts the module docstring, which still says `analysis_plot/` |
| Guard | `len(times) < 2` → skip | Short aborts (tape-not-found, first-cycle E-stop) log at INFO and save nothing |
| Failure policy | `_save_outputs` wrapped in `try/except` | Any plotting exception is logged at ERROR and swallowed — never propagates into the control loop |
| Write order | CSV first, then PNG | Deliberate: data lands on disk before matplotlib is even imported |
| Backend | `matplotlib.use("Agg")` before `pyplot` import | Headless-safe |
| Dependency | `matplotlib>=3.8.0` in `requirements.txt` | |

### 3.3 Figure setup

| Property | Value |
|---|---|
| Construction | `plt.subplots(figsize=(14, 6))` → `ax_rpm`; `ax_err = ax_rpm.twinx()` |
| Output | `fig.savefig(png_path, dpi=150)` → 2100 × 900 px, then `plt.close(fig)` |
| Layout | `fig.tight_layout()` |
| Grid | `ax_rpm` only — `linestyle="--", alpha=0.4` |
| Legend | Manually merged across twin axes (`lines = [line_l, line_r, line_e]`), `loc="upper left"`, `fontsize=9` |
| Zero reference | `ax_err.axhline(0, ...)` — error-red, `linewidth=0.6`, `linestyle=":"` |
| Filenames | `{YYYYMMDD_HHMMSS}_analysisplot.png` and `{...}_data.csv`, timestamp taken **at `stop()`** (end of run, not start) |

### 3.4 Colors — Material Design 500 palette

| Series | Hex | Material name | Axis | Line width | Alpha |
|---|---|---|---|---|---|
| Left RPM | `#2196F3` | Blue 500 | left | 1.0 | 0.85 |
| Right RPM | `#4CAF50` | Green 500 | left | 1.0 | 0.85 |
| Tracking error (mm) | `#F44336` | Red 500 | right | 1.2 | 0.90 |
| Left-axis label + ticks | `#333333` | neutral dark grey | left | — | — |
| Right-axis label + ticks | `#F44336` | Red 500 (matches series) | right | — | — |

Error is deliberately the visually dominant trace: widest line, highest alpha, and its own colour-matched axis so the reader's eye couples the red curve to the red scale.

### 3.5 Axes

| Axis | Label | Limits | Colour binding |
|---|---|---|---|
| X | `Time (s)` | auto (0 → run duration) | default |
| Y-left | `Wheel RPM` | **fixed `0, 2000`** | `#333333` |
| Y-right | `Tracking Error (mm)` | **fixed `-100, 100`** | `#F44336` |

Both Y ranges are hardcoded, which is the right call for run-to-run comparability but has two edges: the ±100 mm error window matches the MGS1600 range so a saturated sensor clips flat at the frame; and the 0–2000 RPM window is sized for AGV A (0.4 m/s ≈ 1273 motor RPM), so an AGV B trace at `OUTPUT_CLAMP_RPM = 100` occupies a narrow band with differential detail hard to read.

### 3.6 Title

Single-line f-string at `fontsize=10`, computed after the series are plotted:

`AGV Auto Run | {timestamp} | Duration={:.1f}s MaxErr={:.1f}mm AvgL={:.0f}rpm AvgR={:.0f}rpm`

`MaxErr` is `max(abs(e))`, `AvgL`/`AvgR` are unweighted means over samples (not time-weighted — with irregular sampling these are biased toward high-sensor-rate stretches).

### 3.7 CSV schema

| # | Column | Format | Source |
|---|---|---|---|
| 1 | `time_s` | `%.4f` | `time.time() - t0` at sample |
| 2 | `error_mm` | `%.3f` | `dbg["e"]` = `error_sign * left_mm` |
| 3 | `left_rpm` | `%.3f` | commanded, post speed-reduction and PID |
| 4 | `right_rpm` | `%.3f` | commanded |
| 5 | `pid_output` | `%.3f` | `dbg["output"]`, post `OUTPUT_CLAMP_RPM` |
| 6 | `d_term` | `%.3f` | `dbg["d"]` = filtered derivative |

Written with `csv.writer` defaults → CRLF line terminator. **`p_term`, `i_term` and `speed_reduction` are computed and available in `dbg` but are not persisted** — they exist only in the DEBUG log line, so any offline term-contribution analysis has to be reconstructed from the text log rather than the CSV.

### 3.8 PID configuration behind the plotted signals

| Key | agv1_kim / agv2_kim | agv_tn (this branch) | Role |
|---|---|---|---|
| `KP` / `TD` / `N` (HIGH) | 1.4 / 0.12 / 20 | 1.56 / 0.1 / 2 | HIGH-speed gain set |
| `KP_SLOW` / `TD_SLOW` / `N_SLOW` | 2.2 / 0.14 / 12 | 1.56 / 0.1 / 2 | SLOW+EXTRA_SLOW set; TN matches HIGH |
| `TI` / `TI_DEADBAND` / `TI_MAX` | 20 / 25 / 500 | 2.5 / 2 / 10 | Deadband-gated integrator, anti-windup clamp |
| `DT` | 0.01 | **0.05** | Loop period; also sets the D filter coefficient `α = dt/((td/n)+dt)` |
| `V_RED_COEF` / `_SLOW` | 4 / 2 | 0.3 / 0.8 | Cornering speed reduction |
| `OUTPUT_CLAMP_RPM` | 800 | **100** | Differential authority ceiling |
| `SR_ALPHA` / `SR_CAP` | 0.15 / 0.55 | 0.08 / 0.2 | Speed-reduction low-pass + cap |
| `ao_max_voltage` | 10.0 (default) | **5.0** | Post-PID voltage clamp |
| `sensor_orientation` | 1 | **−1** | Flips `error_sign` for the rear-mounted sensor |
| `motor_cal` | shared 646.59 / −101.2 | per-wheel L 1261.69/−59.88, R 1254.54/−93.41 | Independent fits, R²≈0.99 |

The branch's headline control change is documented in the `agv_tn` profile comment: `core/pid.py` previously omitted `error_sign` from the derivative term, so with the rear sensor (`error_sign=+1`) D was **anti-damping** and larger `TD` grew the weave. `raw_d` now carries `error_sign`; `TD` was reset to 0.1 as a conservative restart with a documented on-track step plan (0.1 → 0.2 → 0.3).

### 3.9 Logging

**Handler configuration** (`logger.setup_logging()`, called once from `main.run()`):

| Handler | Level | Destination | Rotation |
|---|---|---|---|
| File | `DEBUG` | `logs/agv_{YYYYMMDD_HHMMSS}.log` (new file per process start) | `RotatingFileHandler`, 10 MB × 5 backups, UTF-8 |
| Console | `INFO` (arg `console_level`) | stdout | — |

Root logger is `DEBUG`; handlers do the filtering. Third-party noise is silenced explicitly: `werkzeug` → ERROR, `pymodbus` → WARNING, `can` → WARNING. Format: `%(asctime)s.%(msecs)03d [%(levelname)-8s] %(name)s: %(message)s` with `datefmt="%Y-%m-%d %H:%M:%S"`. Every module uses `logging.getLogger(__name__)`, so `name` doubles as the source tag (`modes`, `_debugging.plotter`, `drivers.can_mgs1600`).

**The per-cycle PID line** — `logger.debug` in `auto_mode`, emitted once per cycle *that had a sensor frame*:

| Field | Format | Meaning |
|---|---|---|
| `[%s]` | `HIGH` / `SLOW` / `EXTRA_SLOW`, or `REVERSE` | Speed mode is the label in forward; direction replaces it in reverse |
| `Target=` | `%.2f` m/s | `current_target_speed` — post-accel-ramp, not the setpoint |
| `e=` | `%+.1f` mm | `error_sign * left_mm` |
| `P= I= D=` | `%+.1f` rpm each | Individual term contributions |
| `out=` | `%+.1f` rpm | Sum, post-clamp |
| `L= R=` | `%.1f` rpm | Final commanded wheel RPM |
| `Vred=` | `%.1f` rpm | Filtered speed reduction |

Actual output from the committed capture:

`2026-05-12 09:45:59.226 [DEBUG   ] modes: [SLOW] Target=0.20m/s e=-14.0mm P=-30.8 I=+0.0 D=+5.6 out=-25.2 L=597.2 R=647.5rpm Vred=14.3rpm`

A second DEBUG line, `[AUTO] left_marker=%s`, is emitted in the same branch on every forward cycle — so forward auto produces **two DEBUG lines per cycle**.

**The `[DIAG]` line** — `logger.info` every `_diag_log_every = 20` cycles, the loop-rate and backpressure instrument:

`[DIAG] cycle avg=49.1ms max=52.6ms (target=50ms) | sensor frames/cycle avg=4.2 max=5 zero=0/20 | qmax ao=6 do=12`

It tracks measured cycle time (avg/max vs `config.DT`), sensor frames drained per cycle (avg/max, plus a starvation counter for zero-frame cycles), and post-enqueue `ao_queue`/`do_queue` depths. It exists specifically to answer whether lowering `DT` is bottlenecked by the controller or by the AO writer / sensor publish rate — the `avg=4.2 frames/cycle` in the capture says the MGS1600 publishes ~84 Hz against a 20 Hz control loop, so there is sensor headroom for `DT=0.025`. Note the inline comment says "~2 s at DT=0.1"; at the TN profile's `DT=0.05` the cadence is actually ~1 s.

**`[PLOT]` lines** — INFO from `_debugging.plotter`: recording started; run-too-short skip with sample count; run ended with sample count and duration; CSV saved path; PNG saved path; ERROR on save failure.

**Two independent log channels.** The `logging` module writes to disk/console; `state.log_event(level, msg)` appends to an in-memory ring buffer (`_EVENT_LOG_MAX`) surfaced at `/errors` and `/api/errors`. Only operator-relevant events are dual-written (tape lost/reacquired, bumper, lidar stop, CAN timeout/recovery, mode/mapping/tuning changes). **The PID loop and `[DIAG]` deliberately do not touch the event log** — the buffer would be flushed of everything meaningful within seconds.

**Volume.** Measured from the committed capture: ~101.5 bytes per DEBUG line, 2 DEBUG lines per forward auto cycle ≈ 203 B/cycle. At `DT=0.05`:

| Metric | Value |
|---|---|
| Write rate | ~4.1 KB/s ≈ 14.6 MB/h |
| Time to fill one 10 MB file | ~41 min |
| Total retention (active + 5 backups, 60 MB) | **~4 hours** |

A new timestamped file is created per process start, so the 5-backup cap is per-run, but old run files are never pruned — `logs/` grows without bound across restarts while any individual run's own history is capped at ~4 h. On a systemd unit with `Restart=always`, a crash loop generates one file per bounce.

### 3.10 Findings — plotting and logging

| # | Finding | Severity | Note |
|---|---|---|---|
| 1 | `PLOT_DIR` is an absolute path containing a hardcoded username | High | Non-portable across AGVs; on a mismatched host `makedirs` raises, is caught, and the run silently produces no data |
| 2 | `recorder.stop()` renders matplotlib synchronously on the event loop | High | Blocks `safety_watchdog` and all drivers for the render duration, at the exact moment of a mode transition or E-stop |
| 3 | `PLOTTING_ENABLED = True` committed | Med | Production default is "always record"; the zero-overhead path is opt-in rather than default |
| 4 | Recorder lists are unbounded | Med | ~72 k samples/h/series; no cap, downsample or ring buffer |
| 5 | Two DEBUG lines/cycle at file level → ~4 h total log retention | Med | A fault reported the morning after is likely already rotated out |
| 6 | `p`, `i`, `speed_reduction` in `dbg` but absent from CSV | Med | Term-contribution analysis requires parsing the text log |
| 7 | Sample series is sensor-triggered, not `DT`-triggered | Med | `time_s` is irregular; naive offline differentiation/FFT will be wrong |
| 8 | Y-limits hardcoded for AGV A | Low | AGV B traces (`OUTPUT_CLAMP_RPM=100`) compress into a thin band |
| 9 | Reverse runs produce plots titled "AGV Auto Run" | Low | No direction, profile, speed-mode or gain-set field in the title or filename |
| 10 | Filename timestamp taken at `stop()` | Low | Filename reflects run end; correlating to the log requires subtracting `Duration` |
| 11 | `_debugging/plotter.py` docstring says `analysis_plot/` | Low | Contradicts `PLOT_DIR` and the actual `_motion_analysis/` output |
| 12 | `_diag_log_every` comment assumes `DT=0.1` | Low | Cadence is ~1 s, not ~2 s, on the TN profile |
| 13 | No PID gain/profile stamp in either artifact | Low | A CSV cannot be attributed to a gain set without matching timestamps against the log |
