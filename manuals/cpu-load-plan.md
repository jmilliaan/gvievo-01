# CPU load plan: N97, LINE + AMCL and NAVIGATION (2026-10-24)

Source: live measurement on the vehicle (idle, LINE, amr.service active, drives "switch on
disabled", AMCL unseeded), two py-spy captures of the 12 Python nodes, and a 7-area code
audit in which every finding was checked against the code by an independent reviewer.
Savings below are the reviewer-corrected figures, in **% of one N97 core at 2.0 GHz**. They
overlap: LeanNode lowers the per-wakeup cost that every rate finding also counts. Treat each
tier's total as the realistic figure, not the sum of its rows.

## 1. Where the CPU goes

| Block | Idle cost |
|---|---|
| Custom rclpy nodes (12 processes) | **~2.1–2.4 cores** |
| Stock C++ (AMCL, EKF, SICK, map_server, lifecycle) | ~0.1 core |
| Kiosk Chromium (all processes) | ~0.10 core |
| Kernel UDP on lo (DDS, ~2,200 datagrams/s each way) | ~0.2 core |
| Dev tooling on the vehicle (VS Code server, agent CLIs) | 0.05–0.23 core |

**Root cause: Humble rclpy executor overhead, not your code.** Each wakeup rebuilds the wait
set in Python, and the cost grows with the node's entity count: subscriptions, timers, 6
default parameter services, and one QoS-event waitable per publisher and subscription. Each
delivered message triggers 2–3 rebuilds (executors.py:478-496). The callback bodies are only
2–11 % of each node's samples. Measured cost is ~1–1.8 ms per wakeup on the N97.

Consequences:
- **Cost ≈ wakeups/s × entities.** The levers are fewer wakeups (rates, mode gating, fewer
  subscribers per high-rate topic) and fewer entities per node.
- numpy, float precision, algorithm tuning, `-O`: negligible. Don't spend time there.
- C++ wins only where a node must wake at a high rate. rclcpp's executor costs about a tenth
  as much per wakeup.
- AMCL won't throttle the box. Parked it's 2 %; moving with the current params expect ~6 %.

Fan-out hot spots, in wakeups per second:

| Topic | Rate | Python subscribers |
|---|---|---|
| `/wheel_states` | 41 Hz | 7 (several only check stillness or freshness) |
| `/amr/panel_state` | 50 Hz | 4–5 |
| `/tf` | 42 Hz | every Python TF listener |
| `/imu/data` | 43 Hz | 3 |
| `/amr/line_track` | 100 Hz | line_follow |

line_follow alone receives ~275 wakeups/s.

## 2. Thermal strategy

- **Keep `no_turbo=1`** (cpu-no-turbo.service). The load is steady periodic work. Turbo
  would only spend more voltage on the same cycles. The 2026-10-02 throttle at 100 °C
  happened with turbo on.
- **Measure before capping.** Run `sudo turbostat --quiet --show PkgWatt,PkgTmp,Bzy_MHz,Busy% -i 30`
  for ≥ 2 h of LINE running with AMCL localized, and note the room temperature. RAPL
  `energy_uj` is root-only, so package watts are unmeasured today.
- Then add a **PL1 backstop at 1.2–1.3 × the measured PkgWatt** to cpu-power-limit.service.
  Today that service only sets PL2 (15 W) and leaves PL1 at 12 W. Don't set 8 W blind. A
  binding PL1 drops the clock below 2.0 GHz and adds jitter. Jitter is safe against
  0.2/0.3 s deadlines but unwanted.
- thermald runs `--adaptive` with no config and only acts near TjMax. Give it an early
  passive trip (e.g. 85 °C) via thermal-conf.xml.
- EPP: keep `balance_performance` until the load is cut, then try `balance_power`.
- No isolcpus / nohz_full. On 4 cores at 75 % load, isolating a core strands capacity, and
  the rclpy nodes aren't RT anyway.
- Optional latency protection: give user.slice `CPUWeight=50` (dev tools, kiosk). Caveat:
  web_node relays the held jog, so don't nice web_node. If niceness is ever added to
  Group.spawn, use `os.setpriority` after Popen, not `preexec_fn` (the supervisor is
  threaded).

## 3. Already in the working tree (other sessions, 09:33–10:06, NOT deployed)

| Change | Est. |
|---|---|
| `amr_base/lean_node.py`: no default QoS-event waitables, applied to 13 nodes | ~25 |
| commissioning_node: timer at idle period with no job (not a 50 Hz early return) | ~9 |
| scan_gate: poll timer armed only while a scan is pending | ~3 |
| amr_web: `/tf` and `/scan` subscribed only while a live view polls | ~11 |
| `AMR_FOXGLOVE=false` in amr.env | 0.3 |
| `deploy/trim-services.sh` (cups, ModemManager, multipathd, …), not yet applied | 0.2 |

Realistic total: **~0.45–0.5 core.**

**Deploy coupling.** `amr_interfaces/msg/LineState.msg` changed, so this needs
`colcon build`, then a restart. A restart deploys *every* uncommitted change: amr_line
tape_run/job/uturn/speed_zone, the line speed toggle, mission files, supervisor and readiness.
Treat it as a vehicle acceptance run, not a CPU tweak.

## 4. Open roadmap

### Tier 1: configuration and operations (no code)

| # | Change | Est. | Notes |
|---|---|---|---|
| 1 | ~~`tape_loc.enabled=false` in production~~. **Withdrawn 2026-10-24.** Tape localization is the production positioning source for stops, starts, slow-downs, junction orders and the U-turn (tracked plan 3 D1). The group stays on in LINE; its cost is cut instead (§4a) | — | |
| 2 | No dev session on the vehicle in production: close VS Code Remote, disable Codex/Copilot remote, `ros2 daemon stop` after CLI probes | 5–23 | Add to RUNBOOK |
| 3 | `logs/pwrbtn-watch.sh`: forks `date` + 7 `awk` every 2 s; its log is 24 MB and unrotated | 1.5 | Use one awk or read sysfs; rotate the log |
| 4 | Kiosk watchdog: python3 + curl + xrandr every 5 s | 1.2 | Slow to 15–30 s; drop the duplicate xrandr probe |
| 5 | Kiosk Chromium: merge the duplicate `--disable-features` (the snap's TFLite flag is lost); add `--disable-background-networking --disable-component-update`; verify GPU raster in chrome://gpu | 0.5 | /usr/local/bin/amr-kiosk-browser |
| 6 | Apply `deploy/trim-services.sh` | 0.2 | |
| 7 | CycloneDDS: participant index / port probing; FragmentSize on lo; `net.core.rmem_max` (265 RcvbufErrors) | 0.2–1 | Reliability more than CPU |

### §4a The tape-localization group in LINE: keep it, make it cheap

Cost today, parked: localization_monitor 18–23 %, scan_gate 10–13 % (it feeds AMCL), AMCL 2 %,
map_server 1 %, lifecycle_manager 1 %. While moving with the default AMCL set, expect AMCL at
~6 %.

Rule from plan 3 §5 M5: **accuracy first.** Anything that changes what AMCL or the locator sees
goes through P0 M1–M6 on the vehicle. Pure transport changes (items a–e) don't change the data,
so they don't need P0.

| # | Change | Est. | Changes the data? |
|---|---|---|---|
| a | localization_monitor: drain the age-only streams (`/scan`, `/imu/data`, `/wheel_states`, `/drives/status`) at its 10 Hz tick instead of one wakeup per message (= item 10) | **8** | No. Ages come from `source_timestamp`; limits unchanged |
| b | localization_monitor: `/scan_gated` is deserialised at 8.6 Hz but used once per 0.5 s `match_period`. Take it raw and decode only the one used | 1 | No |
| c | localization_monitor raycast: stop each beam once it hits, march in chunks (bit-identical output); cache cos/sin per scan geometry | 2.5 | No (identical result) |
| d | scan_gate: raw pass-through (same bytes out, no LaserScan deserialise/serialise) | 1 | No |
| e | localization_monitor and scan_gate: TF listener on its own lean node/thread; no parameter services | 2–3 | No |
| f | AMCL `lean` set (`tape_loc.amcl_params: lean`: 800 particles, update 0.10 m / 0.05 rad) | ~2–3 moving | **Yes. P0 decides** (plan §2.7, M1–M5) |
| g | EKF 50 → 30 Hz (fewer `/tf` wakeups in every Python listener) | 2–3 | **Yes.** odom→base_footprint feeds the locator's stamp lookup. Validate with P0 M4 (latency) |

a–e total ~13–15, which removes most of localization_monitor's idle cost. The group then costs
roughly what AMCL itself costs.

Next C++ candidate: scan_gate, after a–e and a re-profile (Tier 4). It stays on in production,
it's a pure filter, and it sits on the AMCL input path, so a port pays back every hour the
vehicle runs.

### Tier 2: small code changes, behaviour-preserving, offline-testable

| # | Change | Est. | Safety / notes |
|---|---|---|---|
| 8 | panel_node: publish `/amr/panel_state` once per DIO acquisition (20 Hz) plus a 50 ms fallback, instead of every 50 Hz tick. Tick and debounce unchanged | **9** | Panel authority stream. Worst-case gap ~60 ms against 0.2 s consumers (3× margin). Every start/reset edge is still published exactly once. Needs a test |
| 9 | Supervisor: move the 4 high-rate subscriptions (mux, drives, wheels, panel) to a feed node with its own SingleThreadedExecutor | 9 | Same topics, QoS and receipt stamps; freshness windows untouched |
| 10 | localization_monitor: drain the age-only streams (`/scan`, `/imu/data`, `/wheel_states`, `/drives/status`) at its 10 Hz tick instead of waking per message (PolledGroup with `can_execute()=False` plus `take_message`) | 8 | Use `source_timestamp` (cyclone leaves received_timestamp at 0). Moot if #1 is done |
| 11 | Fold the gyro bias into drive_node `_publish_imu`; retire imu_bias_node; publish `/imu/data_raw` only when it has subscribers | 7 | Move gyro_bias.py to agv_core (importing it from amr_localization would create a package cycle). Keep "nothing until calibrated" |
| 12 | line_follow while IDLE/DONE/FAULT, wheels still, no teach recorder: tick at 10 Hz, back to 50 Hz plus `timer.reset()` on any edge or motion | 4 | Start-edge reaction ≤ 20 ms. Wrapper only, autopilot untouched |
| 13 | line_follow: subscribe `/imu/data` only outside IDLE | 4 | |
| 14 | line_follow: derive (v, wz) from `/wheel_states`, drop the `/odom_raw` subscription | 3.5 | |
| 15 | panel_node: skip the `/cmd_wheel_vel` (50 Hz) and `/drives/status` subscriptions when `horn.enabled` is false; take the motion lamp from a 'turning' flag in DriveStatus instead of 41 Hz `/wheel_states` | 5 + 2.5 | |
| 16 | rfid_node: wake on a new tag via a GuardCondition instead of a 50 Hz poll | 3.5 | |
| 17 | cmd_mux: with source NONE and output exactly zero, publish the repeated zero at 10 Hz; any nonzero, first zero or generation change publishes on that tick | 3 | **cmd_mux file: needs a test.** Failure mode: a lost idle zero; drive_node treats >0.2 s as zero anyway (2× margin). Recovery: revert |
| 18 | Compute `/odom_raw` in drive_node; retire diff_drive_odom_node | 3 | One process fewer |
| 19 | `start_parameter_services=False` on nodes nobody reconfigures at runtime (6 entities each) | ~1 per node | Check nothing calls `ros2 param set` on them |
| 20 | amr_web: move the 27 service clients to a second node (~90 → ~27 entities); stop the idle 5 Hz `_live_pose` and 1 Hz reconcile timers; `/drives/pp_status` on demand; `live.py:84` use ceil division (576 → 400 points) | 3–5 | |
| 21 | Small items: drive_node caches its shutdown flag instead of calling `rclpy.ok()` per publish; imu/odom covariance built once; `/drives/pp_status` 4 Hz when idle; supervisor watchdog ping at 1 Hz | ~2 total | |

Tier 2 realistic total: **~0.4–0.5 core.**

### Tier 3: NAVIGATION / MAPPING (projected; validate on the vehicle)

| # | Change | Est. | Notes |
|---|---|---|---|
| 22 | route_executor: LeanNode, no parameter services, TF listener on its own thread. **Keep** MultiThreadedExecutor | 5–10 | The reviewer refuted switching to single-threaded: `wait_for_server` sleeps up to 2 s and would stall the inputs |
| 23 | Nav2 controller_server and behavior_server inactive while the executor is IDLE | 1.5 | Lifecycle |
| 24 | Nav2: one `component_container_isolated` for map_server, AMCL, controller, behavior and lifecycle managers; `bond_timeout: 0` | 1.5 + 1 | |
| 25 | EKF 50 → 30 Hz | 2–3 | Every Python TF listener wakes at the EKF rate |
| 26 | AMCL `lean` set (update 0.10 m / 0.05 rad, ≤ 800–1000 particles) | ~2 moving | **After P0 measurement.** Changing it mid-P1 invalidates the shadow comparison |
| 27 | slam_toolbox: `correlation_search_space_resolution` 0.01 → 0.02; smaller loop-closure search window; `transform_publish_period` 0.1; `map_update_interval` 5 s | 8 + 3 + 4 + 3 | Change one matcher parameter at a time; re-check map quality (the boiacca rev1 corruption is recent) |
| 28 | Web live view in NAV/MAPPING: a 5 Hz display topic instead of raw `/scan` + `/tf` in Python | 5 | |

### Tier 4: C++. Not now

- No port is justified yet. In the control chain the node logic is ~4–6 % against
  ~15–19 % of wait-set work. The fix is wakeups, not language.
- After tiers 1–2, re-profile LINE + AMCL while running. Port only a node still above
  ~10 %, and port only its transport loop. Likely candidates:
  - scan_gate: a pure filter, easy to port.
  - cmd_mux transport only.
- gating.py, panel_io/panel_core, arm_policy, canopen.decide and pp stay in Python as the
  single tested authority. drive_node's CAN bus thread stays in Python.

## 5. Rejected (reviewer-refuted or not worth the risk)

| Idea | Why not |
|---|---|
| `/amr/line_track` 100 → 50 Hz | An unsynchronised 50 Hz follower sees duplicate/double samples, which puts beat noise into the KD term (autopilot.py:216-224, KD dominant). The rate gate `line_min_track_hz` 40 would also be left with only a 1.25× margin |
| IMU poll 50 → 25 Hz | Polls land on ~20 ms bus ticks; one missed SDO gives a 100–120 ms gap, above `imu_fresh_s` 0.1. Wire `imu.poll_period_s` with no value change (sensor-dropout plan P2-1) |
| nanoScan3 `skip: 3` | ~5 %, but it reverses the deliberate 2026-10-02 choice that keeps `/output_paths` at ~17 Hz as the mux field backstop, and adds up to +59 ms before software sees a warning field. User decision; not recommended |
| nginx for /static | ~0 % |
| numpy / float32 / `-O` | Callbacks aren't the cost |

## 6. Projection and acceptance

| State | Custom-node CPU at idle |
|---|---|
| Measured 2026-10-24 | ~2.1–2.4 cores |
| + §3 deployed | ~1.7–1.9 |
| + §4a a–e (tape-loc group kept, transport made cheap) | ~1.55–1.75 |
| + Tier 2 (rest) | **~1.1–1.3** |

While running LINE with tape_loc, add AMCL ~6 % (default set) or ~3–4 % (lean, if P0 accepts
it). Tape localization therefore costs about 0.1 core in production, not 0.45.

Acceptance on the vehicle, sequentially, no dev session attached:
1. Idle 60 s: `pidstat -u 10 6` per process. Compare against the §1 figures.
2. LINE run with AMCL localized, if tape_loc stays on: the same, plus `turbostat` for 2 h.
3. Watch for rate holds (`LineState.track_hz`), panel/lease stale events and FIELD_UNKNOWN
   chatter. Any of these means a rate change went too far: revert that change only.
