# gvievo-01 - AGV line-following controller

Onboard Python controller for the EVOTY differential-drive AGV. Two Oriental
Motor BLV-R drives and a SICK MLS magnetic-line sensor share a 125 kbps CANopen
bus. A physical panel starts automatic travel; a Flask HMI provides held manual
jogging and operating diagnostics. RFID tags identify stations and speed zones.

The existing controller has operated on real hardware. The direction-aware route
and high-speed changes described here require commissioning on that hardware.
This README describes the checked-in code and `profiles/agv-01.json`; historical
run logs retain the parameters and behavior of their own software revision.

## Current profile

| Setting | Value |
|---|---|
| Normal auto cruise | 1000 motor r/min, approximately 0.314 m/s |
| High-speed cruise | 2000 motor r/min, approximately 0.628 m/s |
| Normal/high transition | 500 r/min/s, with existing jerk limiting |
| Slow-zone cruise | 800 motor r/min; requires a configured branch slow zone |
| Manual straight / inner curve wheel / spin | 2000 / 1200 / 300 motor r/min |
| Normal gains | `k_ratio=11.3`, `kd=0.94`, `ki=0` |
| Slow-zone gains | `slow_k_ratio=25`, `slow_kd=5`, blended over `gain_blend_s=0.4` |
| CAN nodes | 1 left, 2 right, 10 MLS; sensor TPDO1 is `0x18A` |
| Nominal control / telemetry / field poll | 50 Hz / 5 Hz / 2 Hz |
| Drive acceleration / deceleration | Manual 1000 / 2000; auto 2400 / 3200 r/min/s |
| Manual / auto watchdog | 0.6 s / 1.5 s |
| Automatic start delay | 0.6 s |
| Standing branch preference | Left; `branch_latch` is currently empty |
| `dry_run` | **false** |

Speeds are derived from 180 mm wheels and a 30:1 gearbox. Steering and speed
reduction can lower actual forward speed; motor limits and configured cruise
speeds are different quantities.

## Operating behavior

**This application can move the vehicle and has no authentication.** Port 5000
belongs on the vehicle's trusted operating network.

| Operator action or condition | Behavior |
|---|---|
| Selector in MANUAL | Automatically arms when permitted; retries unsuccessful arming with backoff |
| Hold a manual arrow or arrow-key combination | Sends `/api/drive` every 100 ms; release sends `/api/stop` |
| Manual commands stop arriving | Zeros the command after 0.6 s; holding again can resume jogging |
| AUTO, then physical Start | Arms, waits 0.6 s, starts or continues the route |
| Reset during a run or pending Start | Stops/cancels the run |
| Reset otherwise | Acknowledges a latched controller fault |
| Selector changes | Stops and disarms; MANUAL can then automatically re-arm |
| Station arrival | Distance-based deceleration, followed by a dwell waiting for physical Start |
| Start at a station | Resumes the same run after the start delay |
| Tape disappears | Coasts within the configured travel grace, then holds the run |
| Tape returns during a hold | Resumes after 2 s of continuously usable tape |
| Drives leave Operation enabled during auto | Holds commands at zero and attempts to re-enable; recovery can resume automatically |

The web API has no `/api/arm` or `/api/auto/run`. `/auto` is a display page.
Manual jogging requires the vehicle already to be armed in MANUAL. Web disarm
is not a persistent inhibit: a selector left in MANUAL maintains arming.
`/api/stop` is the manual setpoint stop, not an automatic-run latch reset.

Panel-started runs refresh their watchdog from valid panel scans, so closing the
browser does not stop them. The legacy opt-in `/api/state?hb=1` heartbeat remains
available and also refreshes the auto deadline. Monitoring pages do not claim it.

`dry_run` concerns the auto path; it is not an offline simulator or a global
manual-motion inhibit. Use the offline tests when no hardware is available.

## Route and station identity

The installation uses a shared line with a balloon U-turn at each end, around
90 m total. Four physical stopping positions deliberately reuse two RFID values.
The route is cyclic, and the first profile row is the assumed startup position.

| Departing station | Departure direction | Next station | Expected arrival tag | High-speed zones allowed on this leg |
|---|---|---|---|---|
| 2 (initial) | Outbound | 3 | `0010` | Yes |
| 3 | Inbound, through upper U-turn | 4 | `0011` | No |
| 4 | Inbound | 1 | `0011` | Yes |
| 1 | Outbound, through lower U-turn | 2 | `0010` | No |

Every station waits for physical Start. Returning to point 2 increments the lap
count; the next Start repeats the cycle. Direction is logical route direction,
not reverse motor motion. Both U-turns are driven forward.

A route row contains `id`, `tag`, `direction`, and `high_speed_to_next`.
`direction` is the **arrival** direction. On departure, the controller adopts the
next station's arrival direction. The direction changes only after the Start
delay completes; cancelling a pending Start does not advance the route.

`stop_until_start_button` supplies `tag`, `direction`, and `stop_distance_m`.
The current distance is 0.4 m for both qualified stop rules. Matching uses the
expected physical station and its direction/tag pair. For example, outbound
travel passes point 4's `0011` before stopping at point 3's `0010`.

The stop profile is computed from software ramp speed. It is not odometric
position control: driver response, steering, and speed reduction affect the
actual resting position. Station arrival retains the active run and CSV across
the dwell.

### State across interruptions

| Interruption | Route state | High-speed latch |
|---|---|---|
| Station dwell | Retained at the confirmed station | Cleared |
| Reset, disarm, end of run | Retained in memory | Cleared |
| MANUAL, then AUTO | Retained in memory | Cleared |
| Line-loss or drive-enable hold | Retained | Cleared; resumes at normal speed |
| RFID connection loss | Retains last confirmed stage; stale encounters discarded | Cleared |
| Controller process restart | Assumes point 2, outbound, waiting for Start | Cleared |

Route state does not track manual relocation. If the vehicle is moved past
stations in MANUAL, the preserved logical position can differ from its physical
position. Restart initialization assumes the vehicle is back at point 2.

### Repeated RFID reads

`tags_seen` remains a raw receive counter. A separate ordered encounter buffer
feeds route and branch decisions:

- Repeated reads of a tag are one encounter until it clears.
- A different tag starts another encounter immediately.
- The same value after `rfid.tag_clear_s` without reads starts a new encounter.
- `tag_clear_s=0.5` is provisional and independent of the HMI's 2 s `tag_hold_s`.
- The departed station's reads are suppressed without suppressing other stations.
- Reconnect discards cached encounters and re-baselines the first fresh tag.
- An encounter-buffer overrun during a run stops it rather than guessing which
  route events were lost.

The former `ignore_t` global station-ignore window has been removed. The loader
rejects that obsolete key. Verify clearance timing against actual reader gaps
and station spacing before running the new route on hardware.

## High-speed zones and control

The same speed-tag pair is reused on both straight high-speed segments:

| Direction | Set high speed | Reset to normal |
|---|---|---|
| Outbound | `0020` | `0021` |
| Inbound | `0021` | `0020` |

Rules live in `high_speed_mode`. The route also gates which legs permit high
speed, so a speed tag on a U-turn leg cannot enable it. Station arrival,
direction change, holds, disarm, and RFID link loss clear the latch.

`autopilot.speed_switch_accel_decel_s=2.0` derives a 500 r/min/s rate from the
1000 r/min difference between normal and high cruise. The existing jerk limiter
remains active, so completion can take slightly longer than two seconds. An exit
received during acceleration retargets the same ramp without jumping its state.
Startup uses the existing acceleration ramp; station stopping uses its own
computed deceleration. Hard stops bypass the cruise transition. Slow-zone mode
has priority over high speed and selects its own steering gains.

The follower scales proportional gain with base speed, filters the derivative,
reduces forward speed with tracking error, and limits wheel commands together.
It prevents derivative kicks after discontinuous track samples. The inner wheel
cannot reverse in auto with the current zero-rpm floor.

| Follower guard | Current value |
|---|---|
| Maximum accepted lateral position | 100 mm |
| Maximum accepted position step | 40 mm |
| MLS freshness timeout | 0.1 s |
| Tape-gap travel grace | 0.075 m, with a derived standstill time limit |
| Integration deadband | 20 mm; integral gain currently zero |
| Control dt bounds | 0.004 to 0.1 s |

RFID encounters are consumed even when a control iteration has no new MLS frame.
The previous wheel command may be retained only while that frame is still
fresh; sensor timeout must still reach the hold path.

A missed high-speed entrance leaves normal speed selected. A missed exit can
leave high speed selected until another reset condition; reused tag values do
not provide independent localization. Exit tags must precede bends by enough
distance for the actual deceleration.

### Branch selection

`core/branch.py` retains the existing steering ladder independently of route
inbound/outbound state. Configured RFID entry tags latch left/right intent;
returning to one track after a fork consumes that order, with exit tags as a
backstop. A slow-zone latch, if configured, lasts until its exit tag.

Straight selection follows the track nearest the previously followed position,
using LCP2 initially. Left/right selects the corresponding extreme track;
`#LCP=7` crossings override branch intent with straight selection. The current
empty branch table uses the standing left preference, including at merges.

## Runtime architecture

| Location | Responsibility |
|---|---|
| `main.py` | Stable entry point and import-path setup |
| `config.py` | Strict profile loading, derived constants, validation, HMI parameter descriptions |
| `canworker.py` | CAN thread, vehicle state, panel policy, route integration, watchdogs and recovery |
| `core/route.py` | Pure route progression and high-speed latch |
| `core/autopilot.py`, `core/kinematics.py` | Steering, speed ramp, body/wheel conversion |
| `core/branch.py`, `core/panel.py` | Branch ladder and debounced panel input edges |
| `drivers/rfid.py` | Chafon TCP thread and tag encounters |
| `drivers/dio.py` | Modbus input/output thread, horn commands and readback |
| `drivers/lidar.py`, `core/lidarframe.py` | nanoScan3 UDP receive, reassembly and decoding |
| `drivers/canbus/` | Shared CANopen primitives and standalone commissioning utilities |
| `core/health.py`, `core/canmon.py` | Device liveness and round-robin drive diagnostics |
| `core/events.py`, `core/runlog.py`, `core/plotrun.py` | Event buffer, CSV, background PNG rendering |
| `core/wifi.py` | Cached Linux Wi-Fi signal readout on the web thread |
| `app/` | Flask routes, local HTML/CSS/JavaScript assets |
| `tests/`, `manuals/`, `logs/` | Offline checks, hardware documentation, recorded runs |

The runtime uses dedicated threads and HTTP polling, not asyncio or WebSockets.
The CAN thread alone owns bus transactions and route decisions. Flask mutates
manual setpoints under a lock or queues slow actions and waits on a Future.
RFID, DIO, and lidar each own their device connection on another thread.

`TpdoTap` routes unsolicited MLS, heartbeat, and EMCY frames while synchronous
SDO calls run. The control loop budgets the remainder of its nominal 20 ms
period; arming and drive recovery include longer blocking transactions while
motion is held. Telemetry runs every 0.2 s; diagnostic SDOs read one object per
node every 0.1 s, completing eleven objects in roughly 1.1 s.

Never perform bus I/O while holding `Controller._lock`: SDO receive can re-enter
sensor callbacks. The RLock is a backstop, and offline structural checks enforce
that bus operations stay outside locked sections.

Layer directories share a flat `sys.path`; they are not packages. Module
basenames must be unique and must not shadow the standard library.
`drivers/canbus/` is a runtime dependency as well as a bench-tool directory.

## Hardware health and stopping boundary

The repository documents the physical stopping chain in
[manuals/safety-chain.md](manuals/safety-chain.md): scanner OSSD and operator
inputs feed the FX3, which controls drive torque removal. Lidar UDP data is a
separate diagnostic stream; its zone mapping is currently marked unvalidated.

Software drive-enable recovery deliberately can resume an active run without
another Start press. CAN status is how the controller observes that transition;
it is not a direct measurement of the reason the hardware chain opened.

Device health reporting and control responses are separate:

- Drive heartbeat/SDO evidence feeds the critical 0.6 s watchdog. Loss stops the
  run and latches a controller fault.
- MLS freshness and tape loss are handled by the follower and its hold policy.
- DIO provides panel scans; valid scans feed panel-started auto liveness.
- RFID health uses connection/carrier state, not silence between station reads.
  Loss clears high speed and prevents accepting cached encounters.
- Lidar data loss is diagnostic; it does not replace the hardware stopping chain.

The horn follows nonzero commanded motion on DO0. Its command is renewed by the
CAN thread and written/read back by the DIO thread. Expiry requests low while the
DIO thread and link are functioning; it is not an independent hardware watchdog.
Shutdown attempts to clear claimed outputs before closing the Modbus connection.

The controller's guarded CAN writes permit controlword, operating mode, ramps,
target velocity and heartbeat time. Manufacturer parameter writes, FREE, clear
ETO, parameter store/restore and controlword fault reset are refused. Normal
CiA 402 re-enable remains possible; the write guard is not a no-resume guarantee.
See [drivers/canbus/guard.py](drivers/canbus/guard.py) and
[manuals/can-monitoring-plan.txt](manuals/can-monitoring-plan.txt).

## Running and configuration

```bash
python3 main.py                     # 0.0.0.0:5000; landing page /auto
python3 main.py --host 127.0.0.1
python3 main.py --port 5001
AGV_PROFILE=agv-01 python3 main.py
```

Only `agv-01` is currently supplied. `AGV_PROFILE` selects an existing JSON file
in `profiles/`; a missing profile is fatal. The loader rejects unknown/missing
keys, invalid direction/tag combinations, duplicate station IDs, conflicting
rule contacts and inconsistent speeds. See `config.py` tuning notes and the
read-only `/params` page. Profile edits take effect after a process restart,
which also resets route position to its first station.

Dependencies are `flask`, `python-can`, `pymodbus` for enabled DIO, and
`matplotlib` for run plots; the slcan fallback also uses `pyserial`. Use the
versions validated on the vehicle: this repository does not pin dependencies.
Matplotlib imports lazily when a completed run is rendered, then remains in the
process. Plot failure is captured in `RunLog.error`; the CSV is independent.

The documented production service is `agv_controller.service`, with an entry
point such as `/home/gvipc-evo-01/agv_can/main.py` and
`Environment=AGV_PROFILE=agv-01`. The service unit is not shipped in this repo.
Its shutdown configuration must reach the application's cleanup path; the
existing deployment uses SIGINT and `Restart=on-failure`.

`/api/restart` refuses while armed and checks the systemd restart policy before
shutting down and exiting nonzero. Do not enable `--debug` autoreload on the
vehicle: it can start another controller process.

The HMI polls `/api/state` every 200 ms. `/manual` is the jog pad; `/auto` shows
route and PID state; `/monitor`, `/io`, `/lidar`, `/alarms`, and `/params` expose
diagnostics and settings. All browser assets are local.

## Logs and verification

An auto run creates `logs/NNNN-auto_YYYYmmdd_HHMMSS/run.csv` and, on close,
`run.png`. Numbering uses the highest directory prefix currently present plus
one. Station dwells remain within the same run. Ordinary stops keep a 2 s
logging tail; disarm closes immediately.

CSV rows include PID terms, command/feedback speed, statuswords, track selection,
route direction, current/next station, dwell state, lap count, speed mode and
speed target. The header records normal/high/slow cruise, gains and ramp values.
Rows are buffered and flushed about once per second on the control thread;
PNG rendering runs separately. Actual-speed feedback is sampled at 5 Hz, so its
resolution differs from the approximately 50 Hz command trace.

```bash
python3 tests/run_all.py             # offline; no device services started
python3 -c "import main"             # import/profile check only
```

The runner pins the test modules and check count. Coverage includes the real
follower against a simulated plant, controller recovery, protocol fixtures,
configuration validation, route laps, repeated equal-valued tags, opposite
travel directions, reconnects, high-speed transitions, and HMI rendering.
Offline results do not validate physical stopping distance or RFID coverage.

Before deploying the route changes, confirm point 2 startup placement, all four
stops in sequence, clearance timing, speed-zone entry/exit in both directions,
and deceleration margin before each bend. Preserve the original run logs as
historical commissioning evidence rather than treating them as tests of this
new behavior.
