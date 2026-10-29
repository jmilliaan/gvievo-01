# External features survey: libraries, OS features and unused device functions

Date: 2026-10-23. Read-only survey. Nothing was run on the vehicle, no service was started or stopped, no CAN frame was sent.

Question asked of every hand-built engine in the stack: is there a maintained library, a Humble package, an OS feature or an unused function of the fitted hardware that should replace, augment or configure it? Every candidate was checked by a verifier against the installed packages, the local manuals and the code. Where the verifier corrected a fact, value or effort, the verifier wins and the entry says so. Downgraded entries are marked **downgraded**.

Related plans: `manuals/sensor-dropout-hardening-plan.md` (cited as "plan P0-x / P1-x / P2-x"), `manuals/mls-marker-plan.md`, `manuals/tracked-plan-3-tape-localization.md`, `manuals/tracked-speed-plan-1-no-slam.md`, `manuals/obsolete/map-merge-plan.md`. Many candidates turned out to be refinements of items already in those plans; those are folded in, not duplicated.

---

## 0. Summary

The owner's answers to this survey's questions and the build order are in
`manuals/unified-coding-plan.md` §1 (2026-10-25).

### Top 10

| # | Feature | Target engine / file | Mode | Value | Effort | Why |
|---|---|---|---|---|---|---|
| 1 | Foxglove bridge locked to read-only (whitelists, capabilities; clientPublish only for `^/initialpose$`) | `supervisor_node.py:1013-1018` argv, `launch_helpers.foxglove()` | configure | high | S | The stock 3.5.0 config lets any LAN client publish `/amr/manual_command`, call supervisor services and set node parameters. That includes the sick driver parameters, whose callback sends a CoLa2 write to the nanoScan3. Bypasses the web role check and R12. |
| 2 | Freeze the platform: ROS apt source on `snapshots.ros.org/humble/2026-09-14`, pin live `packages.ros.org` to -1, hold the HWE kernel metas | `/etc/apt` (files tracked in `amr_ws/deploy/`), apt-mark | replace / configure | high | S | All 266 installed ros-humble packages match the 2026-09-14 snapshot exactly. Today any `apt install` can pull a partial Humble sync; GA 5.15 metas have 5.15.0-198 pending. |
| 3 | Move the whole set to the 2026-10-12 snapshot for tf2/tf2_ros 0.25.24 (ABBA deadlock fix), then A/B `scan_gate` | ros-humble set; `scan_gate.py`, `nav2_params.yaml:86-92`, `slam_mapping.yaml` | configure | high | S (procedure M) | 0.25.23 (installed 09-15) carries the waitForTransform lock inversion; hangs began 09-17. Best root-cause candidate for the slam_toolbox 0 % CPU hang and the controller_server TF freeze. |
| 4 | MLS yaw rate on TPDO7 with 1806h:05 event timer, frame-age fallback to SDO | `mls_imu.py`, `read_imu.py`, `guard.py` SENSOR_ALLOWED | configure | high | M | Removes the 50 Hz synchronous IMU SDO from the bus thread. Fixes a latent bug (`enable_tpdo` writes only :01, :05 ships 0 = no transmission) and an unguarded write in `read_imu`. |
| 5 | nanoScan3: continuous UDP output saved in Safety Designer (human), plus driver `State` diagnostics and `status_overview` as stop explanations | Safety Designer project; new pure `scanner_health.py`; web alarms | configure | high | M + S | The driver's CoLa2 method-176 write is volatile; after a scanner power cycle UDP never returns (upstream issue #72). Contamination, device error and "config not verified" are unexplained today. |
| 6 | Always-armed rosbag2 snapshot recorder (black box), dumped on FAULT/stop edges | new supervisor process group `blackbox`; `reports.py` | new | high | M | No evidence exists for an unattended stop unless `run_log.sh` was pre-armed. Humble 0.15.17 has `--snapshot-mode`; low-rate topics only. Three areas proposed it independently. |
| 7 | `amr.service` comes back after a CAN adapter re-plug (`After=`/`WantedBy=canable@can0.service`), plus a `reset-failed` sudoers verb | `amr_ws/deploy/amr.service`, `amr-web.sudoers`, `validate.sh` | configure | high | S | A `BindsTo=` stop is a clean stop, so `Restart=on-failure` never fires. Better target than plan P1-4's can0 device unit. |
| 8 | RFID liveness heartbeat on 0x0072 (documented getter) instead of 0x0050 ("initialize") | `agv_core/drivers/rfid.py` Heartbeat; profile `rfid.heartbeat_s` | augment | high | S | Unblocks plan P1-11 without sending an opcode of unknown side effect; gives continuous `param_mismatches()`. |
| 9 | Serve the HMI with waitress (apt `python3-waitress` 1.4.4) | `amr_web/web_node.py:33` | replace | high | S | Werkzeug 3.1.8 always sends `Connection: close`; every 100 ms jog refresh pays a TCP handshake over Wi-Fi, the path where 14 of 17 holds died. |
| 10 | Read-only E-stop/STO evidence: FX3 spare Q4 → DIO DI09, and BLV-R 60FDh bit 3 (HWTO) mapped into a TPDO | FX3 project (human); profile DIO map; `canopen.py` TPDO steps; `DriveStatus` | new | high | S + M | Replaces "E-stop guessed from torque loss" (`job.py:398-402`, plan M2). No safety-path change: explanation only. |

Close behind (high value, not in the ten): monotonic freshness clocks in the mux (plan P0-7, already specified), Nav2 lifecycle `is_active` polling after COMMIT, BMS passive COB census, platform manifest in validate/report, odometry calibration (UMBmark + wall-referenced pivots), Hypothesis stateful tests for `gating.py`, `fake_output_paths` driven by field geometry, rosbag2 replay fixtures, survey recording for offline slam_toolbox replay.

### Found during the survey (fix regardless of the ranking)
- **Two guard.py bypasses exist in bench tools.** `read_imu.enable_tpdo` (`read_imu.py:382`) writes through `drive_forward.sdo_write`, and `drive_forward.sdo_write` (`agv_core/drivers/canbus/drive_forward.py:64-144`) never calls `guard.check`. Both break "every SDO/RPDO write goes through guard.py". Standalone fix, no library needed.
- **Foxglove parameter path reaches the scanner.** `sick_safetyscanners2`'s parameter callback calls `changeSensorSettings` (CoLa2 data-output write) when host_ip/port/angles change. Default Foxglove allows parameter writes from the LAN.
- **RUNBOOK reverse speed wording.** `RUNBOOK.md:413` says "half the speed cap", which reads as 0.4 m/s. Code is 0.5 × 0.60 = 0.30 m/s (`route.py:23,57`, `compiler.py:177`). Fix the text; pin 0.30 m/s in a test.
- **AMCL `save_pose_rate` is dead in Humble nav2_amcl 1.1.20.** `amcl.yaml`'s 0.5 does nothing.
- **`nanoscan3.yaml` comment is wrong.** `intrusion_data` is not the field-status source; `/output_paths` comes from application data.
- **DIO module identity.** The repo says CK-EC5163 (EtherCAT series); the Modbus-TCP 16 DI + 12 relay model is CK-TP5163.
- **apt timers have been disabled since ~2026-08-28**, so nothing (security included) installs unattended, and nothing records that.
- **iTCO hardware watchdog is blacklisted** by the Ubuntu HWE package (`/lib/modprobe.d/blacklist_linux-hwe-6.8_*.conf`).
- **slcan gives zero error counters.** `ip -details` reports 0 bus-errors on can0 because the CANable2 slcan firmware never reports them; 0 means "unknown", not "clean".
- **python-can error frames collide with EMCY routes (latent).** python-can 4.6.1 subscribes to error frames by default; a non-EFF error frame's `arbitration_id` can be 0x081/0x082, the EMCY routes of nodes 1/2. Inert on slcan, real on a gs_usb/peak_usb adapter.
- **N97 throttles at ~65 °C reading.** `package_throttle_count` 4200 in ~3 h on cpu0, max episode 29 ms; the HMI shows a comfortable temperature.

### How the survey was built
11 areas inventoried from the code (can-drives, mls, line-engine, mission-nav, localization-maps, supervisor-ops, gating-motion, hmi-tooling, peripherals, sim, ecosystem), plus 4 gap areas opened during research (BMS on can0, N97 power-management latency, package/kernel drift, I/O truth vs electrical sheets). Each candidate was researched online and in the local manuals (BLV-R CANopen and function manuals, SICK MLS OI 8021642, SICK TI 8022708, CF821 vendor manual, CK-TP5163 datasheet), then adversarially verified against installed binaries and source. **163 candidates: 138 kept (63 as proposed, 75 downgraded), 25 rejected.**

### Conflicts between candidates, settled here
- **Drive TPDO3 is claimed twice** (`blvr-tpdo3-tpdo4-monitor` and `blvr-tpdo3-hwto-speeddev`). Only TPDO3/TPDO4 are free. Recommended split: TPDO3 = 60FDh u32 + 407Bh u32 (both state words, type FFh, inhibit ≥ 50 ms, event timer 1000 ms); TPDO4 = 407Ch i16 + 407Dh i16 + 40A4h i16 + 603Fh u16 (inhibit 500 ms, event timer 500 ms). 6077h, 4075h, 406Bh/406Ch stay in the SDO monitor slot. This is the survey's reconciliation, not a verified layout: bench-check before relying on it.
- **MLS TPDO budget is 4 active.** TPDO1 (track) + TPDO7 (gyro) = 2. TPDO2 (line level/width) only if tape_health shows `track_level` too coarse.
- **Bus load is measured at ~440 f/s ≈ 45 % of 125 kbps** (`amr_ws/README.md:198`), not the ~40 % some candidates assumed. SYNC (+50 f/s) is not justified.
- **Re-plug target:** `canable@can0.service` (this survey) over `sys-subsystem-net-devices-can0.device` (plan P1-4). The device unit appears before `ip link set up`.
- **Snapshot file behaviour in Humble rosbag2:** each snapshot rolls to a new file (0.15.13 backport), but `metadata.yaml` is written only at recorder exit. Reindex (`ros2 bag reindex`) or read the `.mcap` directly.

---

## 1. Inventory

Hand-built engines per area, as found in the code. "Why" is the repo's own stated reason, shortened.

### can-drives
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| DriveLink (CiA 402 link/power, PC-loss guard) | `amr_base/canopen.py:300-1035` | DISARMED → STANDBY → ARMED, 1016h consumer, TPDO-measured counts | No rclpy; injected bus so sequences are asserted without hardware; every write via guard.py |
| `decide()` policy table | `canopen.py:1091-1153`, `drive_node.py:432-529` | Pure (state, wants, faults) → action | Tabled in tests; FAULT left only by explicit ack |
| Router + expedited SDO client | `canopen.py:233-285`, `verify_drivers.py:26-90` | COB-ID dispatch; blocking SDO with echo match | Pushed frames must not be lost during transfers; ID-collision window |
| PDO layer + scaling | `rpdo.py`, `canopen.py:62-230,636-690` | RPDO1 6040h/60FFh; TPDO1 6041h/606Ch; TPDO2 6064h/1001h | Removed 3.6 ms of SDO per tick; mapping is a privileged write, deny-list applied recursively |
| guard.py | `agv_core/drivers/canbus/guard.py` | Allow-list + FORBIDDEN for drives and MLS | One stray frame can defeat safety behaviour; assessor-facing |
| pp blind-move controller | `amr_base/pp.py` | Commissioning moves in the drive's position loop | Decide without a bus; pp safety config read back, never written |
| drive_node bus thread | `amr_base/drive_node.py` | One thread: services, decide, setpoint, heartbeat, MLS, IMU, monitor | Single owner; heartbeat reflects a live controller |
| canmon SDO round-robin | `agv_core/canmon.py` | 11 vendor objects per drive | Diagnostic only; a burst would blow the 20 ms tick |
| Alarm/state decode | `drivers/canbus/alarms.py`, `agv_core/alarms.py` | EMCY, NMT, statusword, 85-code operator catalogue | Pure tables shared by bench and web; never gates motion |
| Bench tools | `verify_drivers.py`, `verify_bus.py`, `bus_health.py`, `drive_forward.py`, `lss.py` | Scan, identity, SDO soak, LSS | slcan gives no error state; soak is the substitute |

### mls
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| read_mls + decoders | `drivers/canbus/read_mls.py` | TPDO1 Standard/Combi decode per 2006h:01 | Read-only; decode by reported variant, not assumption |
| MlsTrack | `amr_base/mls_track.py` | TPDO/SDO/auto acquisition, NMT Start node 10 | Writes no config; SDO queue never holds the setpoint |
| MarkerDetector | `amr_base/marker_events.py` | Marker code edges → `/amr/line_marker` | FailSafe codes can last one 10 ms frame |
| MlsImu | `amr_base/mls_imu.py` | Yaw rate from 2034h:03 (TPDO7 if enabled) | Decode by reported 1A06h mapping; receive-time stamps |
| read_imu | `drivers/canbus/read_imu.py` | Bench IMU read, bias/noise | Gyro-odometry mitigates gearhead backlash |
| Gyro bias + imu_bias_node | `amr_localization/gyro_bias.py` | Wheel-gated stationary bias | EKF fuses rate only, cannot estimate bias |

### line-engine
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| LineFollower | `amr_line/autopilot.py` | Tape PID, Kp = K_RATIO·v, S-curve | Verbatim port of the controller that ran the vehicle |
| Branch ladder | `amr_line/branch.py` | LCP1-3 selection, seal-in latches | Rung-for-rung transcription, diffable against drawing |
| TrackReader | `amr_line/track.py` | Freshness and rate gate | SDO fallback measured 9.8 Hz vs 50 Hz PID |
| runtime config | `amr_line/runtime.py` | 34 names from profile | Node, test and sim construct it differently |
| SpeedZone + CurveGuard | `amr_line/speed_zone.py` | HIGH only after outer→inner markers | Every failure ends at NORMAL |
| UTurn | `amr_line/uturn.py` | Encoder-gated pivot, MLS-closed centring | 2026-10-08 field failures |
| FollowJob | `amr_line/job.py` | LINE authority/hold FSM | Testable without a ROS graph |
| TapeRun, TagTable, MarkerReader | `tape_run.py`, `tag_table.py`, `marker_reader.py` | Once-only encounter cursors, stops | Site mission semantics |
| Trip / CallQueue | `amr_line/trip.py` | Site-103 trips | Site rules D3-D11; never moves anything |
| Tape graph, locator, teach, store, health | `tape_graph.py`, `tape_locator.py`, `tape_teach.py`, `tape_graph_store.py`, `tape_health.py` | Teach-and-repeat, 1-D Kalman, revisions | Plan 3 D3/D4; same transaction as map bundles |

### mission-nav
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| Route executor | `amr_mission/route_executor_node.py` | One Nav2 action at a time on drawn routes | Nothing may insert a path the operator did not draw |
| Run FSM | `amr_mission/run_fsm.py` | Run states, resume | Pure, spec §7.1 |
| Goal attempts | `amr_mission/goal_attempts.py` | Action-goal lifecycle barrier | Review R08/Q06 |
| Route schema + compiler | `amr_navigation/route.py`, `compiler.py` | Canonical YAML, map-hash binding | Editor and executor share it |
| Validator + footprint sweep | `validate.py`, `footprint.py` | Exact swept footprint approval | Complete swept area, not samples |
| Stores | `store.py`, `map_bundle.py` | Immutable revisions | fsync + hard-link publish |
| Survey moves | `survey_move.py` | Preset moves during mapping | Slow repeatable motion helps the matcher |
| Mapping session | `mapping_session_node.py` | Survey FSM around slam_toolbox | Pause service is a stateless toggle |
| Nav2 params + launch | `nav2_params.yaml`, `navigation_layer.launch.py` | RPP, Spin, rolling costmap | No planner/BT/smoother by design |

### localization-maps
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| Readiness FSM | `amr_localization/readiness.py` | UNLOCALIZED/CHECKING/READY/LOST | Covariance cannot establish the aisle; operator confirms |
| Monitor + scan consistency | `localization_monitor_node.py`, `scan_consistency.py` | Independent scan-vs-map check | Mesh cage seen through is not a pose error |
| Scan gate | `scan_gate.py`, `scan_gate_node.py` | Release scans once TF exists | MessageFilter async path hung slam_toolbox |
| Gyro bias | `gyro_bias.py`, `imu_bias_node.py` | See mls | |
| Relocalizer | `amr_maps/relocalize.py` | ±1.5 m/±30° search before continue-mapping | slam_toolbox welds a bad start pose |
| Grid I/O | `amr_maps/grid.py` | PGM/YAML, raster, masks | No ROS/OpenCV deps; hardened parser |
| Map edits | `amr_maps/edit.py` | Replayable polygon ops | Deterministic replay |
| Map bundles | `map_bundle.py` | Staged, hashed, atomic | Partial save can never look approved |
| Map merge (planned) | `manuals/obsolete/map-merge-plan.md` | Grow base map | Existing tools lack gates/provenance |
| Stock-node config | `amcl.yaml`, `ekf.yaml`, `slam_mapping.yaml` | Tuned integration | Beamskip, no recovery, rate-only yaw |

### supervisor-ops
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| Supervisor node | `amr_bringup/supervisor_node.py` | Groups, lease, transactions | Async operations with ids |
| Mode FSM | `mode_fsm.py` | Admission + transaction steps | Pure, snapshot-fed |
| Process groups | `process_supervisor.py` | setsid groups, bounded stop | Own pgid per role |
| Readiness snapshots | `readiness.py` (bringup) | Generation-tagged last-message store | Replaced layer's READY never survives |
| OperationBook | `operations.py` | Idempotent operation records | Browser retry never duplicates |
| Unclean-shutdown marker | `uptime.py` | Power cut vs service crash | Actions differ after each |
| sd_notify + unit | `sdnotify.py`, `deploy/amr.service` | READY/WATCHDOG/STOPPING | Ten lines, no python-systemd dep |
| Log rotation | `logs.py` | Rotate/cap role logs | base.log reached 43 MB |
| Deploy tooling | `deploy/install.sh`, `validate.sh` | Install without enabling/starting | Witnessed cutover only |
| Domain guard + DDS | `domains.py`, `cyclonedds-local.xml` | Domain 10 vs sim; loopback | Fake base on the live domain |
| Owner locks | `agv_core/ownerlock.py` | flock per device | OS allows two can0 openers |
| Disk guard | `agv_core/disk.py` | Refuse survey start/save only | Never gate a moving vehicle on disk |
| Events + event log | `agv_core/events.py`, `amr_web/eventlog.py` | Edge events, persisted | Dependency-free |
| Run recorder | `tools/run_log.sh`, `bag_report.py` | Pre-armed MCAP + domain metrics | Tape/U-turn/RFID metrics |

### gating-motion
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| Gating / source arbitration | `amr_base/gating.py` | Which source drives each tick | Authority from lease, panel, permit, never the stream; expiry is zero at once |
| Field speed shaping | `gating.py`, `cmd_mux_kinematics_node.py`, `scanner_fields.*` | Zero/scale AUTO from `/output_paths` | Scanner-evaluated outputs, not point clouds |
| Mux: slew, S-curve, IK | `cmd_mux_kinematics_node.py`, `diff_drive.py`, `agv_core/kinematics.py` | Shape and clamp | Limits never above the drive's 6083h |
| Wheel odometry | `diff_drive_odom_node.py` | `/odom_raw` from 6064h | Custom CANopen node, not ros2_control |
| EKF config | `ekf.yaml` | vx + vyaw, gyro vyaw | Gyro drifts 3.4°/min absolute |
| Panel I/O | `agv_core/panel.py`, `panel_io.py`, `panel_node.py` | Debounce, edges, re-baseline | Held-at-power-on and reconnect hazards |
| Commissioning | `blindrun.py`, `commissioning.py` | Encoder-only measurement moves | Measure before SLAM relies on them |
| URDF | `amr_description` | TF tree + footprint | Minimal |

### hmi-tooling
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| Flask app + async ops | `amr_web/server.py`, `web_node.py`, `amr.js` | ~70 endpoints | ROS-free server via Adapter |
| RosAdapter | `adapter.py` | Snapshots + bounded service calls | One node, typed calls |
| Browser jog | `jog.py`, `jogpad.js` | Held-not-latched ticketed teleop | Safety invariant |
| Live view | `live.py`, `png.py`, `liveview.js` | Map/pose/scan | Lazy PNG encode |
| Standing alarms | `amr_web/alarms.py` | Worst-first rows, headline | One derivation for all pages |
| Event log | `eventlog.py` | Persist events | Restart lost the stop reason |
| Report zip | `reports.py` | One-button post-mortem | Verbose belongs on disk |
| Commissioning log | `commissioning_log.py` | Commanded vs measured | |
| Role guard | `role.py` | Engineer PIN | Mistake guard, not security |
| Header indicators | `wifi.py`, `netcheck.py`, `adapter.read_ipc_temp` | Wi-Fi, temp, disk | |
| Demo page / demo server | `demo.py`, `tools/demo_server.py` | Visitor page; offline app | No ROS on a laptop |
| Foxglove bridge | supervisor argv | Engineer 3D view | Stock package, default config |

### peripherals
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| RfidLink + rfid_node | `agv_core/drivers/rfid.py`, `rfid_node.py` | CF821 TCP driver, encounters | Vendor SDK is a Windows DLL; driver never changes reader settings |
| rfid_survey | `rfid_survey.py` | Read-quality survey | Read-only by construction |
| DioLink + panel | `drivers/dio.py`, `panel.py` | 50 ms Modbus-TCP scan, expiring coil claims | Input image + expiring commands |
| lidarframe (dormant) | `agv_core/lidarframe.py` | Passive nanoScan3 UDP decoder | sick driver writes CoLa2 output config at start |
| Scanner integration | `nanoscan3.yaml`, `scanner_fields.*` | Driver launch, field model | Scanner config is the authority; humans only |
| COM1 RS-485 | `manuals/Neu-X102-N97_RS485_interface.md` | Desk research | Documentation only |

### sim
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| Fake base + WheelModel | `amr_sim/fake_base_node.py` | Replaces drive_node | Mirrors drive-node topics |
| Fake IMU | `fake_imu_node.py` | Biased raw gyro | Measured D-3 noise model |
| Fake panel | `fake_panel_node.py` | PanelScan semantics | Same msg as the real adapter |
| Scan synth + raycast | `scan_synth_node.py`, `amr_maps/raycast.py` | `/scan` from ground truth | numpy only |
| Tape synth + plant | `tape_synth_node.py`, `tape_plant.py` | MLS reading on straight tape | Re-hosted plant |
| Square driver | `square_drive.py` | Scripted open-loop square | Deliberate closing error |
| Sim world | `generate_sim_factory.py` | 30 × 20 m deterministic world | |
| Sim launch + unified tests | `sim.launch.py`, `test_unified_sim.py` | Layer-1 swap; P7 end-to-end | ~3 min mechanism run |
| Demo server | `tools/demo_server.py` | See hmi | |

### ecosystem (cross-cutting)
| Engine | Files | Purpose | Why hand-built |
|---|---|---|---|
| Supervisor/lease/authority | `supervisor_node.py`, `mode_fsm.py` | Mode and motion authority | FSM decides, node acts |
| Alarm catalogue + events + report | `agv_core/alarms.py`, `events.py`, `reports.py` | 85 codes, clears_by | Codes are message fields |
| Site mission + trip engine | `agv_core/mission.py`, `missions/site-103.json` | Tape AGV jobs | Site rules |
| Tape graph / locator | see line-engine | | |
| Map/route stores | see mission-nav | | |
| HMI (only external interface) | `amr_web` | No northbound fleet interface | Site D5: no central system |
| Domain/DDS guards, owner locks | see supervisor-ops | | |
| Field interpretation | `scanner_fields.py` | Software copy of field set | Explain stops only |
| RFID driver + radio state | `rfid.py` | Reader on US region | Vendor tool owns settings |

The four gap areas (BMS on can0, N97 power management, package/kernel drift, I/O truth) had no hand-built engine to inventory; they were opened because research found unowned risk.

---

## 2. Recommendations by area

Format per candidate: verdict, mode, value/effort after verification, Humble status, then what / sources / target / sketch / risks. Downgraded entries keep only what survives.

### 2.1 can-drives

#### `blvr-tpdo3-tpdo4-monitor`: health objects pushed on the unused TPDO3/TPDO4
**Keep.** configure · value medium (was high) · effort S · Humble: n/a (drive firmware)
- **What:** map 407Bh/407Ch/407Dh/40A4h/603Fh (and optionally 6077h) into TPDO3/4 with slow event timers plus change-of-state. Today a full SDO sweep takes 5.5 s standing still, 22 s moving.
- **Sources:** `manuals/bldc/opman_can/blvr_canopen.md` p.31-32 (max 4 entries / 8 bytes per PDO, mapping only in Pre-operational, types FEh/FFh), p.77-87 (1802h/1803h, 1A02h/1A03h; inhibit in 100 µs, event timer ms), Appendix p.123 (PDO=Yes for these objects), p.12 (Save=Yes only via 1010h, so the mapping is volatile).
- **Target:** `agv_core/canmon.py`, `canopen.py` prepare() remap block (:636-690) and Router handlers, `drive_node.py` monitor slot (:833-838).
- **Sketch:** add the two PDOs to `configuration_steps()` inside the existing pre-op/rollback window; Router decoders feed the canmon store; `canmon.snapshot()` unchanged; SDO slot keeps only rare objects (409Bh, 406Ch, 4073h/4075h, 4056h, 40A2h, 1003h). Use the TPDO split in §0 "Conflicts" so TPDO3 also carries 60FDh. Test: mapping steps pass guard; canmon decodes packed frames. Update the stale `canmon.py:20-22` rationale.
- **Risks:** guard already admits 1800h-19FFh and 1A00h-1BFFh by rule; no deny-list change. Read-only diagnostics, outside the safety path. Do not put 6077h on a fast PDO.
- **Verifier:** value lowered: 5.5 s thermal/voltage trends were already adequate; the gain is pushed 407Bh/603Fh edges and a lighter monitor slot. Adds ~14 SDO writes per drive to a prepare() that already has ~25 and blocks the single bus thread; keep it compact or land after plan P0-6 bounds sensor work. Measured bus load ~440 f/s ≈ 45 %.

#### `blvr-407B-information-bits`: decode 407Bh as Information status (compatible)
**Keep.** configure · value medium (was high) · effort S · Humble: n/a
- **What:** early warnings below alarm level (INFO-DRVTMP/MTRTMP/LOAD/TRQ/WATT/VOLT-H/VOLT-L) and configuration drift (INFO-REBOOT/CONFIG, DSLMTD/IOTEST = MEXE02 remote operation on a drive in service).
- **Sources:** function manual p.334 (reg 246/247 NET-ID 007Bh; 4000h+NET-ID pattern), p.345 (compatible layout = Information status 0), p.347 (bit table), p.467-470 (causes, auto-clear, RAM-only history).
- **Target:** `agv_core/canmon.py:56-64` (provisional), new INFO table in `agv_core/drivers/canbus/alarms.py`, operator catalogue.
- **Sketch:** pure `INFO_BITS` table and `decode_info(u32)` producing rising/falling edges in a clock-fed module; canmon publishes edges as DiagnosticStatus WARN. Closes plan P1-1 A6 (no edge events). Thresholds stay MEXE02-owned (4xxxh denied).
- **Risks:** diagnostic only, must never gate motion. A short pulse can be missed between samples; TPDO3 change-driven push fixes it.
- **Verifier:** the CANopen manual labels 407Bh sub 00h "Information status 1" (`blvr_canopen.md:4142`), and Modbus Information status 1 (NET-ID 0571h) is a different register. The status-0 layout and the word order are inferred; confirm both once on the bench against the MEXE02 information monitor before trusting the decode. INFO-CAN-WNG is in status 2, not in 407Bh.

#### `cia402-quick-stop-release`: Quick stop for release()
**Downgraded** (value high → low) · configure · effort S
- **What survives:** read 6085h, 605Ch and 605Bh back in pv preflight and refuse to arm when the two drives disagree.
- **Sources:** `blvr_canopen.md` p.99-100 (605Ah default 2, 605Bh default 0 = immediate stop, 605Dh, 605Eh), lines 1673-1674 (Quick stop/Halt valid with Remote bit 0).
- **Verifier:** this vehicle's 6085h is 1600 r/min/s (RUNBOOK:599, profile `quick_stop_decel`), half the pv decel of 3200, so Quick-stop release roughly doubles stopping distance. Shutdown-at-speed is already handled by plan P1-6 (keep waiting on nodes that answer) and P0-5(3) (release failure gets fault() semantics). Halt in pv frames adds nothing (60FFh = 0 travels in the same frame). If a post-timeout primitive is still wanted, Disable operation (0x07) with 605Ch default 1 = slow-down ramp is the closer fit; 605Ch is Save=Yes, so read it back.

#### `blvr-bootup-reboot-detect`: NMT boot-up frame and 40A2h/40A9h
**Downgraded** (value high → medium) · configure · effort S
- **What survives:** a DRIVE_REBOOTED FAULT reason when the Router sees boot-up (0x700+n, data 0x00, already decoded at `canopen.py:443-447` but unused), and a boot-count/uptime record (40A2h number of boots, 40A9h continuous uptime ms) in preflight and diagnostics. Backstop: 40A2h increase or 40A9h decrease since last seen = reboot.
- **Sources:** `blvr_canopen.md` p.21 §4.3, p.22 §4.5, p.67 (1017h Save=Yes), p.93.
- **Verifier:** the stale-EMCY-latch clear and 1017h re-apply are already specified (plan P0-5(1), P1-6); a reboot while ARMED is already caught as missing TPDOs. Say in the DRIVE_REBOOTED text that the drive also lost its 1016h consumer guard until the next prepare(). No auto re-engage: FAULT still needs the operator ack.

#### `blvr-alarm-history-8130h-facts`: read 603Fh and 1003h in preflight
**Keep.** configure · value medium (was high) · effort S
- **What:** 603Fh = newest entry of the 16-entry non-volatile alarm history (+FF00h), so the cause of the last stop survives the operator's power cycle. 1003h is the volatile CiA 301 list (10 entries, lost at power-off).
- **Sources:** `blvr_canopen.md` p.61 (1003h, empty → abort 0800 0024h), line 4386 (603Fh); function manual p.459 (16 NV entries with snapshots), p.451 (alarm 81h "Reset by ALM-RST: Possible"), p.460 (sub code 8130h).
- **Target:** canopen.py preflight, `verify_drivers.py`, canmon (or via TPDO4).
- **Sketch:** preflight reads 603Fh and 1003h:00..n per drive and logs them; canmon carries 603Fh. 4041h-404Ah (pattern for history 1-10) are undocumented in the OD: probe read-only on the bench; abort = absent. No timestamp or counter is exposed over CANopen.
- **Risks:** no software reset: 40C0h and controlword bit 7 stay denied; 1003h:00 writes stay unadmitted.
- **Verifier:** ALM-RST is not wired on this vehicle and the BLV-R has no front-panel ALM-RST button (it is an assignable input). So `clears_by=power_cycle` for 8130h is correct today; the operator text must not mention an ALM-RST button. Whether to wire one is the open user decision in plan Q4.

#### `sync-sampled-tpdo`: SYNC-sampled TPDO1/2 with a drive as SYNC producer
**Downgraded** (value medium → low) · configure · effort M
- **Sources:** `blvr_canopen.md` p.21 §4.4, p.62-63 (1005h/1006h, 250 µs multiples), p.32 (TPDO type 01h-F0h); canopen.readthedocs.io/en/latest/sync.html.
- **Verifier:** rpdo.py rejected SYNC for wire load (50 f/s on a bus at ~45 %), not CPU; a drive producer does not change that. The TPDO2 dithering storm is already solved by inhibit = period. The skew bias is small against wheel slip that AMCL corrects, and irrelevant in LINE. It needs a guard.py change (1005h/1006h value rules) and couples one drive's reboot to the other's feedback. Use kernel RX timestamps (`kernel-rx-timestamps-odometry`) instead. 1005h is PDO=No, default 0000 0080h, Save=Yes.

#### `bcm-deadman-heartbeat`: count-limited SocketCAN BCM heartbeat
**Downgraded** (value medium → low) · configure · effort S
- **Sources:** docs.kernel.org/networking/can.html (BCM); python-can 4.6.1 `socketcan.py:437-464, 537-545`.
- **Verifier:** mechanism is sound (duration → count, ival2 = 0), but `keepalive()` already runs before every DriveLink read/write (`canopen.py:450-500`). The remaining gap is one SDO wait of up to 0.4-0.5 s against a 500 ms 1016h; shortening those timeouts closes it. A BCM task adds an (N-1)·100 ms window in which a hung process still looks alive. Kernel behaviour after count expiry is from bcm.c, not the docs. Only the disarm ordering (`canopen.py:775-780`) is not bench-proven.

#### `python-canopen-bench-and-lss`: python-canopen 2.4.1 for bench tools
**Downgraded** (value medium → low) · augment · effort M · PyPI only (MIT), already in `~/.local`, not a rosdep key
- **Verifier:** facts correct (single TX choke point `Network.send_message`, LssMaster present), but segmented upload for 1008h-100Ah is ~40 lines in the existing client, MLS LSS support is unconfirmed, and a frame-level GuardedNetwork is a second guard to keep in sync. The `drive_forward.py` guard bypass (`:64-144`) is real and is fixed independently (see §0). Do not adopt `BaseNode402` (its `reset_from_fault` writes bit 7).

#### `can-adapter-real-error-counters`: kernel-native adapter (PEAK PCAN-USB) instead of slcan CANable2
**Keep.** replace · value medium · effort M · Humble: n/a (peak_usb in stock 6.8 HWE)
- **What:** TEC/REC, ERROR-WARNING/PASSIVE/BUS-OFF transitions, restart-ms and hardware RX timestamps on can0. Replaces the 400-read SDO soak as the wiring verdict.
- **Sources:** local `peak_usb.ko` symbols (berr counter, restart, ts info); candleLight_fw README (STM32G431 CANable 2.0 not supported); lkml July 2026 gs_usb series (host bus-off recovery not in 6.8); `lsusb` shows CANable2 slcan firmware 16d0:117e.
- **Target:** `bus_health.py`, `drive_node.open_bus()`, host `canable@.service` + `70-canable.rules`, `amr.service` BindsTo.
- **Sketch:** drop slcand; bring can0 up with systemd-networkd (`[CAN] BitRate=125000`, `RestartSec=100ms`); bus_health reads `ip -j -d -s link show can0` plus drive EMCY 8120h/8140h. Keep the slcan fallback for bench laptops (but see `canopen-localnode-vcan-emulator` on the fallback hazard).
- **Risks:** purchase + deploy change; bench session only when asked. Link-level bus-off restart does not clear drive FAULT; that still needs the operator ack.
- **Verifier:** "6.8 gs_usb lacks do_set_mode" could not be confirmed from module strings; treat as unverified. The 6.8 slcan.ko does have `slcan_bump_err`; the limit is the CANable firmware. Fits plan P1-4/P2-5.

#### `router-bus-stats-diagnostics`: per-COB rates and bus-load estimate in the Router
**Downgraded** (value medium → low) · new · effort S · can-utils 2020.11.0 installed
- **What survives:** per-COB frame rates and a bit-stuffing load estimate (canbusload method) in a pure `busstats.py`, published in the existing 1 Hz DiagnosticArray. Fold into plan P1-3.
- **Verifier:** TX-error counting, decode-error counters and loop-overrun stats are already P1-3 and P0-6(e); SDO RTT is P2-5. Sysfs error counters stay zero on slcan.

#### `kernel-rx-timestamps-odometry`: use python-can kernel RX timestamps
**Keep.** configure · value low · effort S
- **What:** stamp TPDO samples with `msg.timestamp` (SO_TIMESTAMPNS, CLOCK_REALTIME) instead of `time.monotonic()` at decode (`canopen.py:416-426`); WheelStates header from the older of the pair; optional interpolation of the leading wheel.
- **Sources:** python-can 4.6.1 `socketcan.py:641-649, :792`.
- **Risks:** realtime clock can step: never use it for freshness or watchdogs; keep monotonic there.
- **Verifier:** only the socketcan path (slcand netdev) gets the kernel stamp; the python-can "slcan" serial fallback stamps in userspace. Cheap alternative to SYNC; also needed by the MLS gap detector's tight threshold.

#### `can-flight-recorder`: in-process CAN frame log
**Keep.** configure · value medium · effort M (was S)
- **What:** post-mortem record of every can0 frame for 8130h trips, R04 unconfirmed stops and ETO dropouts, readable by candump/Wireshark. Nothing in the repo logs frames today.
- **Sources:** python-can 4.6.1 `SizedRotatingLogger`, `CanutilsLogWriter`, `BLFWriter` (python-can.readthedocs.io file_io).
- **Sketch:** Router puts frames on a bounded queue; a writer thread drains it, drops and counts when full, never blocks the bus thread; copy the current file on a FAULT edge. Profile `canlog.enabled/max_bytes` with schema, validation and refusal test.
- **Verifier:** the writer thread competes for the GIL with the 20 ms bus thread, not just CPU. Measure tick jitter with the P0-6(e) overrun counter first; prefer BLF or a binary ring dumped on a FAULT edge over continuous text at ~440 f/s.

#### `touch-probe-marker-latch`: 60B8h touch probe latched at a marker/RFID edge
**Downgraded** (value medium → low, effort M → L) · new
- **Verifier:** default 60B8h = 3131h is first-event mode, so re-arming needs a denied 60B8h write; whether MEXE02 can set and persist continuous mode is unconfirmed; USR-LAT-IN0 assignment is a 4xxxh parameter; the CF821 has no confirmed digital output; markers come from the MLS over CANopen, so there is no separate 24 V marker output to wire. No plan reports a LINE stop-accuracy problem from bus latency. See also rejected `blvr-touch-probe`.

### 2.2 mls

#### `mls-tpdo7-gyro-stream`: yaw rate on TPDO7 with event timer
**Keep.** configure · value high · effort M (was S) · Humble: n/a (MLS FW V5)
- **What:** every gyro sample with its own sensor stamp, no synchronous IMU SDO on the bus thread, about half the bus time of 50 Hz SDO polling.
- **Sources:** SICK MLS OI 8021642.1OC7 (2024-10-25) §8.1.1 Table 4 p.29-30 (1806h:01 default 0x80000000, :05 default 0), §8.1.2 Table 5 p.36 and Table 16 p.40 (TPDO7 = gyro x,y,z INT16 + u16 ms stamp, fixed mapping), §8.1.3 p.40 ("A value of 0 deactivates the transmission"), §8.6.7 p.56.
- **Target:** `mls_imu.py` start/_on_tpdo/poll, `read_imu.py` enable_tpdo (~382), `guard.py` SENSOR_ALLOWED, `tests/test_canmon.py`.
- **Sketch:** bench (service stopped, `--go`, owner lock): write 1806h:05 = 20 then 1806h:01 = 0x28A via `guard.check_sensor`, NMT reset node 10, read back, power-cycle once to prove persistence. `SENSOR_ALLOWED += (0x1806,1), (0x1806,5)`. Runtime: also read :05 (0 = stay on SDO); frame-age watchdog (no TPDO for 5 periods → SDO, log once), which is plan P2-11. Active MLS TPDOs become 2 of 4.
- **Risks:** `guard.py` is safety-listed: state the failure mode (a wrong entry lets the bench tool change the IMU stream, never a drive or the track; `check_sensor` is node-specific, FORBIDDEN first) and recovery (write 1806h:01 back to 0x80000000, NMT reset; mls_imu drops to SDO). Keep 20 ms.
- **Verifier:** (1) the latent bug is real: `enable_tpdo` writes only :01 and goes through `drive_forward.sdo_write` without `check_sensor`. (2) mls_imu decodes by 1A06h, which the manual does not list ("mapping is fixed") and has never been read on this unit; read it on the bench, or fall back to the Table 16 layout when it aborts. (3) `test_canmon.py` asserts no SENSOR_ALLOWED index is `guard.is_allowed()`; 1806h is allowed for drives (PDO comm range), so narrow that check deliberately and update `EXPECTED_CHECKS`. (4) mls-marker-plan row 73 recorded the decision to keep the IMU on SDO; update it. 1010h:01 = 2 as auto-save is a CiA 301 reading; persistence is unproven until the power cycle. `tune_mls.py` does not exist (`read_imu.py:5`).

#### `mls-tpdo-period-gap-detector`: exact-period TPDO gap detection
**Downgraded** (value medium → low) · augment · effort S
- **What survives:** fold into plan P1-8. New facts: §8.1.3 allows only 0xFE/0xFF and 1800h:05 defaults to 10 ms, so P1-8's "disable while stationary if on-change" clause can go and `ABORT_GRACE_FRAMES` can be derived from the period read at start.
- **Verifier:** "strictly periodic" is inferred (§7.3.3 mentions CoS and inhibit). A 1.5× threshold is only sound with kernel timestamps, which the Router does not pass today; P1-8 proposes 3×. Check an inter-frame histogram from an existing bag first. False gaps only suppress markers (speed falls to NORMAL).

#### `mls-imu-stamp-liveness`: IMU stamp as an MCU-alive counter
**Downgraded** (value medium → low) · augment · effort S
- **Verifier:** manual facts hold (100Ch/100Dh "Node guarding not supported", no 1014h, 1017h aborts on this unit). The substance is already P1-7 (frozen stamp) and P1-8 (byte-identical TPDO1 diagnostic-only). Only the "MCU alive" proxy is new, and it proves nothing about the track pipeline. Depends on TPDO7.

#### `mls-imu-init-and-axes`: blank 640 ms after sensor start; raw axes independent of 2027h
**Keep.** augment · value medium · effort S
- **What:** after a sensor reboot the gyro reads exactly zero with fresh receive times for 0.64 s, published today as real "not rotating" with variance 1e-6 (the F04 class), and able to poison a bias window. Separately, the raw gyro frame is fixed by hardware, so the "CCW reads positive" check cannot be invalidated by a later 2027h change.
- **Sources:** MLS OI §8.6 p.54 (640 ms, all outputs zero), §8.6.7 p.56 (Sensor Flipped has no influence on raw data), §8.4.2 p.43.
- **Target:** `mls_imu.py`, `drive_node.py:148` gyro_sign comment, `gyro_bias.py`.
- **Sketch:** drop samples for `IMU_INIT_S = 0.64` (manual constant, not a tunable) after a trigger, and drop any x=y=z=0 sample with stamp 0. Fake-clock test in `test_mls_imu.py`.
- **Verifier:** in SDO mode a brown-out does not pass through `start()` (rediscovery runs only from mode off). The trigger must be a stamp reset or backward jump (needs per-sample stamp: TPDO7 or lower `stamp_every`) or mls_track's stream-return signal. The stamp itself may be zero during init.

#### `mls-tpdo2-line-level-width`: TPDO2 line level and width
**Downgraded** (value medium → low) · new · effort M
- **Verifier:** TPDO2 (Table 11) and 0.048 mT LSB confirmed, and it does fix E3's sampling-rate objection, but it costs the third TPDO slot, two more allow-list entries (same `test_canmon` conflict), a LineTrack change with colcon build, and bus load. Do it only if tape_health or E0.6 shows `track_level` too coarse. Width is likely UINT8 (max 255 mm); this unit's 1801h:05 reads 10; default COB 0x8000028A, and 0x38A is the TPDO3 base.

#### `mls-marker-direction-geometry`: direction is marker geometry
**Downgraded** (value medium → low) · augment · effort S
- **What survives:** sharpen bench B6 to 4 cases × 2 drive directions (code 1 on +, code 1 on −, code 3 normal, code 3 mirrored), log the raw 5-bit field and byte 7, record 2027h with every result. Direction = side of the larger-offset marker after inversion (§8.5 p.52), i.e. vehicle heading vs layout, not motion. No code until B6 (D6 stays).
- **Verifier:** B6/D6 and the raw field already exist; that the meaning is the same in standard/extended/FailSafe is inferred.

#### `gyro-bias-persist-seed-bound`: persist and seed the gyro bias
**Downgraded** (value medium → low) · augment · effort M · no ROS 2 package does wheel-gated bias
- **What survives:** the plausibility bound (0.5 °/s, refuse a 1 °/s window) under plan P1-7. Skip seeding.
- **Verifier:** the 2.3 s without `/imu/data` happens at boot when the vehicle is still and cannot move without Start; BiasEstimator already re-estimates on every still window. Seeding adds runtime file state, cross-node temperature plumbing, serial matching and two schema keys to save ~2 s. fusioncore (23-state UKF, Humble/Jazzy, Apache-2.0) exists but needs absolute heading (GPS); robot_localization has no bias state.

#### `mls-slow-diag-objects`: unused MLS diagnostic SDOs
**Downgraded** (value low) · augment · effort S
- **What survives:** one line in the `read_mls` snapshot for 2070h:02/03 (lifetime max/min temperature, RO INT8, p.35). Note in the diagnostics plan that line_good uses its own FieldLevel hysteresis (on > 500, off < 400), separate from 2025h.
- **Verifier:** 1001h is "No error output" (p.28). 2024h queued after a field event reads the recovered field, not the minimum; `read_mls` already reads 2024h on the bench (`:327, :390`).

#### `mls-interference-variant`: TPDO1 variant 4 if B7 fails
**Keep.** configure · value low · effort S · conditional on bench B7 failing
- **What:** variant 4 "Standard enhanced compensated" = Standard packing + interference suppression + improved diverter detection; the manual recommends it for floor interference fields. 3 → 4 keeps the TPDO1 packing.
- **Sources:** MLS OI §8.1.2 Table 10 p.39, §8.4.6 p.51.
- **Sketch:** `read_mls set-variant 4 --go` (2006h:01 already allow-listed), power cycle, profile `mls.variant = 4`, re-run B3/B4/B7. No guard or code change.
- **Verifier:** 202Dh:02 is documented as "Last level" (default 30 %), while the interference section says the slope is set via 202D.2. Confirm on the bench which meaning applies under variant 4; it affects the marker plan's "detection levels unchanged" assumption.

### 2.3 line-engine

#### `balise-linking-overdue`: expected-next-anchor windows (ETCS linking)
**Downgraded** (value high → medium, effort M → S) · augment
- **What survives:** a per-anchor window (a + b × distance from the designed spacing between mission rows) instead of plan P0-9's flat `max_tag_gap_m`. Build it inside P0-9 (tape_run/TagOdometer), not as a new `linking.py`. Start wide (0.3 m + 3 %).
- **Sources:** ERA terminology "linking"; Subset-026 3.6.4.3/3.6.4.7 via BAV CR782 memorandum; `agv_core/drivers/rfid.py:65`.
- **Verifier:** already designed twice: plan P0-9 (missed-tag backstop, hold `rfid_overdue`) and tracked-plan-3 D5/§2.3/§2.4 (3σ anchor windows, unexpected-fork hold). Drop ANCHOR_EARLY for RFID on line-a: known unknown-tag clusters (0060/0040) would cause nuisance stops. Holds only, released by physical Start.

#### `curvature-preview-taught-graph`: curvature preview from the taught graph
**Downgraded** (value high → low, effort M → L) · augment
- **What survives:** a P2 idea for steering feed-forward only, behind HEALTHY plus a σ gate, off by default, as a deliberate `autopilot.py` port edit.
- **Verifier:** steady corner error is κ/K and speed-independent (speed plan 1 §1), so a radius speed cap does not fix R 0.5 tracking; HIGH already ends before corners. FF needs the locator in closed loop (P1 is shadow-only, site-103-only; line-a has no S). A 3-point fit over 0.3 m with 5 cm taught spread is too noisy (straights read as R ≈ 1 m). Raise `k_ratio` in steps (14, 16) with kd 1-1.5 first.

#### `fx3-moc-speed-monitoring`: FX3-MOC drive monitor with speed-switched fields
**Downgraded** (value high → medium) · new · effort L · safety hardware, configured by a person only
- **What:** SLS, SDI, SS1/SS2 and speed/direction-dependent nanoScan3 field switching (FX3-MOC0 1062344 speed only; FX3-MOC100000 / FX3-MOC100010 1112300).
- **Sources:** SICK datasheet FX3-MOC100010; Flexi Soft Drive Monitor family overview; FX3-MOC online help im0055077; `io-mapping.md:59` (only FX3-XTIO fitted).
- **Verifier:** not a prerequisite for HIGH: a fixed field validated at 0.85 m/s is the planned route (speed plan 1 D2/§7, README:277-279), and the MOC is already the "later" item there. Needs encoders the BLV-R does not expose and full re-validation. PL e / Cat 4 per axis only with two encoders; a single sin/cos with voltage monitoring gives PL d. Does not authorise raising any cap.

#### `mls-gyro-heading-checks`: gyro heading signature at forks
**Downgraded** (value medium, effort S → M) · configure
- **What survives:** branch half only. A bias-corrected gyro Δheading over the fork episode compared against each candidate leg's taught Δheading, as an AMCL-independent second opinion feeding the existing latched `wrong_branch → LOST` hold. `/imu/data` is already bias-corrected and `line_follow_node` already subscribes. Site-103 / plan-3 scope; needs expected Δψ per leg in the compiled Route; moving `wrong_branch_*` thresholds (dataclass defaults `tape_locator.py:53-56`) to the profile needs schema + refusal test.
- **Verifier:** the U-turn half is weak: the 2026-10-08 failure was a stall on the tape bulge, not slip, and is fixed by the no-crawl rule and spin-time limit.

#### `sensor-driven-tick`: tick on MLS sample arrival with a watchdog timer
**Keep.** augment · value medium · effort S · plain rclpy (EventsExecutor is not in installed Humble rclpy)
- **What:** the 50 Hz MLS event timer and the 50 Hz node timer beat; some PID steps see no new sample and the next sees two, so derivative-on-measurement sees 0 then 2×. Ticking on each new LineTrack gives one sample per step and true dt, and up to 20 ms less latency.
- **Sources:** `line_follow_node.py:227,279,398,615`; `autopilot.py:211-224`; docs.ros.org Humble executors.
- **Target:** `amr_line/line_follow_node.py` (_on_track/_tick); `autopilot.py`, job and authority unchanged.
- **Sketch:** in `_on_track`, `reader.update()` then `_tick(now)` if TPDO-sourced and ≥ 0.5·dt since last tick; keep `create_timer(dt)` as a watchdog that ticks only if no sample-driven tick for 1.5·dt. Min-spacing guard against bursts. SDO-fallback samples never drive ticks. Fake-clock node test.
- **Verifier:** measure first, cheaply: log the fraction of ticks that saw no new seq. Mux and drive_node resample downstream, so the latency gain is partial. Authority re-check stays ≥ 33-50 Hz.

#### `rt-sched-preempt-full`: preempt=full + SCHED_FIFO for control nodes
**Downgraded** (value medium → low) · new · effort S
- **What survives:** step 1 only, folded into the sensor-driven-tick measurement: log tick period and LineTrack inter-arrival p50/p99/max for a shift. Step 2 only if p99 > 5 ms or rate holds appear.
- **Verifier:** kernel facts hold (6.8.0-138 HWE, PREEMPT_DYNAMIC, voluntary, HZ 1000), but no record of jitter-caused rate holds exists. Kernel cmdline is set via GRUB, not netplan. SCHED_FIFO on a Python process covers all its threads including the can0 bus thread, so LimitRTTIME is mandatory; preempt=full costs throughput against the < 75 % CPU go rule.

#### `rear-mls-heading`: second MLS behind the axle
**Downgraded** (value medium → low) · augment · effort L
- **Verifier:** LINE never follows tape in reverse (U-turn pivots), so half the benefit is unneeded. Heading term = deliberate port edit + sensor + wiring + a new node id through `check_sensor`. Bus +5-6 %. Cheaper levers first (k_ratio, later FF). No MLS heading output exists; Roboteq MGS1600GY has none; Naviq MTS160 measures angle at 1° (already in speed plan 1 literature). Revisit only if NORMAL corner tracking fails after the K steps.

### 2.4 mission-nav

#### `nav2-fault-reporting-plugins`: typed abort cause via thin C++ wrapper plugins
**Downgraded** (value high → medium) · augment · effort M · interfaces present in apt Nav2 1.1.20; upstream error codes are Iron+
- **What:** COLLISION_AHEAD / NO_PROGRESS / TF_FAILURE / EMPTY_PLAN / COSTMAP_EXTENT / SPIN_TIMEOUT per attempt, so the "collision ahead?" auto-retry (`route_executor_node.py:1187-1197`) applies only to a real collision.
- **Sources:** installed `FollowPath.action` (result Empty); Humble `controller_server.cpp`, RPP source; `nav2_rotation_shim_controller.hpp` (primary_controller pattern); `spin.hpp`.
- **Sketch:** new ament_cmake `amr_nav_plugins`: FaultReportingController wrapping RPP (forward every call, especially `setSpeedLimit`), ReportingProgressChecker, ReportingSpin (`onCycleUpdate` is public). Publishes `amr_interfaces/ControllerFault`; executor matches by goal stamp. Do not parse `/rosout`.
- **Verifier:** current harm is ≤ 3 retries behind 2 s `auto_resume_clear_s` plus a misleading message; torque/field checks already precede the retry. Costs: first C++ package, new msg + colcon build, N97 build time, ABI lock to Nav2 1.1.20 (add a validate.sh rebuild check). Worth it mainly with `along-track-goal-checker`, which shares the package.

#### `along-track-goal-checker`: half-plane goal checker (Humble backport of AxisGoalChecker)
**Keep.** replace · value medium (was high) · effort M (was S) · not in Humble (AxisGoalChecker is Lyrical/Rolling)
- **What:** FollowPath succeeds when the robot crosses the endpoint's normal plane within a cross-track tolerance. Removes the 4.5 cm overshoot pose (`route_executor_node.py:197`) and the executor's along-track cancel (`:1141-1147`).
- **Sources:** api.nav2.org AxisGoalChecker; Humble `nav2_controller/plugins.xml` (Simple, Stopped, Position checkers: all circles); Humble `controller_server.cpp`.
- **Sketch:** `amr_nav_plugins::AlongTrackGoalChecker`, two instances (`end_fwd`, `end_rev`), chosen per chain through `FollowPath.Goal.goal_checker_id` (hardcoded `'precise'` at `:897`). Picker is a pure unit-tested function. Keep the overshoot fault (length + 2·tol) and the settle verify as independent checks.
- **Verifier:** the executor writes vehicle heading on every pose and keeps forward heading on reverse steps (~823), so the axis must come from the step direction. README says 0.025 while the yaml says 0.05. Effort is M as the first C++ package.

#### `vector-pursuit-controller`: Vector Pursuit as an A/B FollowPath plugin
**Keep.** augment · value medium · effort S · apt `ros-humble-vector-pursuit-controller` 1.0.2 (Apache-2.0)
- **What:** pursuit law with heading-from-path; tighter convergence onto a straight than RPP at the same lookahead. Low CPU.
- **Sources:** index.ros.org vector_pursuit_controller; github blackcoffeerobotics/vector_pursuit_controller; apt candidate 1.0.2-2jammy.20260915.
- **Sketch:** second `controller_plugins` entry `FollowPathVP` mirroring route.py caps (desired 0.60, accel at mux limit); set `use_rotate_to_heading false`, `allow_reversing true`, `use_heading_from_path true` explicitly; `max_linear_accel` lowered from 2.0. Profile key `navigation.controller_id` (schema + refusal test) passed as `FollowPath.Goal.controller_id`. Extend `test_nav2_params.py` to mirror VEHICLE_V_MAX/W_MAX. A/B on the vehicle with existing cross-track and endpoint metrics.
- **Verifier:** `setSpeedLimit` is implemented (source, master = Humble VCS branch). Throws PlannerException on collision like RPP. README default for `use_heading_from_path` is false, source true; README sets `approach_velocity_scaling_dist` twice. Does not fix endpoint semantics. Trial at most one alternative controller.

#### `graceful-controller-humble`: nav2_graceful_controller for station stops
**Downgraded** (value medium → low) · augment · effort S · apt 1.1.20, not installed
- **Verifier:** `setSpeedLimit` exists; collision via simulateTrajectory, but a costmap transform failure returns cmd_vel unchecked and off-costmap counts as free. Steers to a point ~1 m ahead, cutting chained R ≥ 1 m arcs against a 0.05 m margin. Goal completion still uses the circle checker. Along-track checker fixes endpoints more directly; overlaps the VP trial.

#### `slam-pause-state-param`: read `paused_new_measurements`
**Downgraded** (value medium → low) · configure · effort S · slam_toolbox 2.6.10
- **What survives:** read the parameter back after each Pause toggle to close the one real gap: `_call()` timing out after the toggle applied leaves `_slam_paused` inverted (`mapping_session_node.py:141, :161, :610-617`).
- **Verifier:** `mapping_layer.launch.py` wraps slam_toolbox and the session in `required()`, so a slam restart takes the session down; no other Pause client exists.

#### `lifecycle-event-bringup`: drop TimerAction delays, disable silent respawn re-activation
**Keep.** configure · value medium · effort S · Nav2 lifecycle_manager 1.1.20
- **What:** `attempt_respawn_reconnection: false` on both managers, so a false bond miss under N97 load no longer hard-resets AMCL and silently restarts it, or aborts an active run that the executor then retries as "collision ahead?". Removing the 3 s / 6 s TimerActions is minor.
- **Sources:** Humble `lifecycle_service_client.cpp` (blocking wait_for_service), `lifecycle_manager.cpp` (bond_timeout 4.0, bond_respawn_max_duration 10.0, attempt_respawn_reconnection true; reset(true) on bond break).
- **Target:** `navigation_layer.launch.py:165-175, :211-220`; `nav2_params.yaml` and localization manager params; `test_launch_layers.py`.
- **Verifier:** the supervisor checks `is_active` only during bring-up (`supervisor_node.py:884`), not at runtime; with respawn off, runtime loss is caught indirectly unless `nav2-lifecycle-health-after-commit` lands. Production autostart is false (supervisor drives STARTUP). Contract test needs a new assertion (the walker already looks inside TimerAction).

#### `rclpy-nonblocking-action-checks`: `server_is_ready()` and stamp-age-checked TF
**Keep.** configure · value low (was medium) · effort S · rclpy 3.3.22
- **What:** `_send()` calls `wait_for_server(2.0)` inside the 10 Hz tick under the RLock (~925); `_pose()` (`:474-479`) never checks the TF stamp. Replace with `server_is_ready()` + a pure debounce helper raising EXEC_ACTION_FAILED after a grace, and a pose-age limit (start ~0.5 s, settle on vehicle).
- **Verifier:** impact is modest: the stall happens only when the server is already missing (faults anyway; expired permit zeroes the mux). New grace/age values are node parameters unless deliberately moved to the profile (then schema + refusal test). The goal_attempts barrier stays.

### 2.5 localization-maps

#### `tf2-0-25-24-abba-fix`: tf2/tf2_ros 0.25.24
**Keep.** configure · value high · effort S · apt Humble main (candidate 0.25.24-1jammy.20260915; installed 0.25.23)
- **What:** 0.25.23 introduced a lock-order inversion between `Buffer::waitForTransform` and `BufferCore::testTransformableRequests`; it triggers when a MessageFilter waits for a transform while `/tf` keeps arriving (the "scan 20-40 ms ahead of odom" case). Symptoms match 2026-09-17: slam_toolbox executor dead at 0 % CPU, controller_server TF listener frozen.
- **Sources:** github ros2/geometry2 issue #992; Humble tf2_ros CHANGELOG (0.25.24 2026-09-15 backport #982/#990); local dpkg/apt history (stack first installed 2026-09-15 17:00).
- **Target:** `scan_gate.py`/`scan_gate_node.py`, `slam_mapping.yaml` scan_queue_size workaround, `nav2_params.yaml:86-92`.
- **Sketch:** move the whole ros-humble set to the 2026-10-12 snapshot (never tf2 alone; see `ros-snapshot-apt-source`, `lvm-snapshot-staged-move`). Keep `/scan_gated` first; then point one consumer (local costmap) at raw `/scan` for a long run; then slam_toolbox in a survey. If stable, shrink scan_gate to a thinning stage or delete it.
- **Risks:** planned deploy with rollback; focused tests + one unified sim, sequentially. Prove on the vehicle before deleting scan_gate.
- **Verifier:** the fix was maintainer-reviewed and merged (PR #982 approved by tfoote, mini-1235, ahcorde; backport #990); issue #992 itself is still open. #992 does not mention slam_toolbox; the link rests on symptoms and timeline.

#### `sick-time-offset-backdate`: negative `time_offset` on the nanoScan3 driver
**Keep.** configure · value medium (was high) · effort S · installed sick_safetyscanners2 1.0.5
- **What:** the driver stamps at UDP assembly (`now + time_offset`), about one sweep after the first ray. Set ~-0.018 s (mid-sweep of the ±95° window) so the scan stamp lands inside published odom history.
- **Sources:** SICKAG `MessageCreator.cpp`; LaserScan.msg; `nanoscan3.yaml` (time_offset 0.0); `slam_mapping.yaml:29-36`.
- **Sketch:** set, measure scan_gate hold time and expired count on the vehicle, document the value in `nanoscan3.yaml`.
- **Risks:** host-side parameter only; no CoLa2 write; OutputPaths has no header, so mux `/output_paths` freshness is unaffected.
- **Verifier:** after the tf2 fix the remaining gain is latency and registration. Bigger effect than the cited 3 mm: a 30 ms stamp error while turning at 0.5 rad/s is ~0.9° of yaw (SLAM smear). Published rate ~17 Hz (skip 1); scan_time still ~30 ms. Age-checking consumers (monitor scan staleness 0.15 s, web live view, mapping_session) gain ~18 ms apparent age: harmless, say so in the yaml. Use raw_data DataHeader timestamps sampled offline once to estimate jitter.

#### `rl-predict-to-current-time`: robot_localization `predict_to_current_time` + `smooth_lagged_data`
**Keep.** configure · value medium · effort S · installed robot_localization 3.5.4
- **What:** odom→base_footprint published at "now" each 50 Hz cycle instead of the last measurement time. Pair with `smooth_lagged_data: true`, `history_length: 0.5`. Keep `transform_time_offset: 0`.
- **Sources:** humble-devel `ros_filter.cpp` (~l.441/476, 619, 721-731, 875); params/ekf.yaml; strings of installed `librl_lib.so`.
- **Verifier:** confirmed in source. Twist rejection thresholds are optional and risky: odom0 fuses vyaw too, so a Mahalanobis gate can reject real turns when gyro and wheels disagree; settle on logs. Replay CPU of a 15-state C++ EKF is negligible. Verify with `tf2_monitor odom base_footprint` and scan_gate stats.

#### `dt-raymarch-field`: distance field + sphere tracing for scan_consistency/raycast/relocalize
**Keep.** augment · value medium (was high) · effort M · numpy only (range_libc itself unmaintained)
- **What:** one clipped distance field per map revision (cached by sha256) replaces the half-cell march (~460k lookups per compare), the shift-loop dilation and the relocalizer proximity field.
- **Sources:** github kctess5/range_libc; Walsh & Karaman CDDT (ICRA 2018); Felzenszwalb & Huttenlocher (2012); `raycast.py:57-75`, `scan_consistency.py:24-35`, `localization_monitor_node.py:177-178`.
- **Sketch:** pure `amr_maps/distfield.py` (`build`, `march`); `raycast.cast()` keeps its signature; brute force kept as test oracle (|diff| ≤ 1 cell). Also add an "endpoint in unknown/off-map" fraction to the consistency check (known gap). cv2 only lazily (map-merge plan §4.5).
- **Verifier:** measured 29 ms per `cast()` at 1152 beams to 10 m on 2319×1203, every 0.5 s ≈ 6 % of a core. Monitor caps range at 10 m (~400 samples per ray). A bounded 8-neighbour chamfer overestimates by up to ~8 %, so step = max(DT − half-cell diagonal, half-cell) or rays jump one-cell walls. Zero-code interim: subsample beams (AMCL uses 180). Re-check `min_scan_match`/`max_scan_long` on vehicle logs.

#### `bnb-correlative-matcher`: branch-and-bound correlative matcher for relocalize
**Downgraded** (value high → medium, effort M → L) · augment
- **What survives:** NAVIGATION-mode assisted LOST recovery is a separate feature that can be built on today's `relocalize.match()`, operator-initiated and confirmed, AMCL recovery left at 0.
- **Verifier:** slam_toolbox humble `ProcessAgainstNodesNearBy` indeed welds regardless of response, so relocalize.py is the only guard. But it was built 2026-10-23 and has not run on the vehicle; brute force is a one-shot action nobody measured as slow; Python BnB is hard to vectorise; exact runner-up maxima need a weaker bound. Defer until vehicle trials show the window or runtime is insufficient.

#### `amcl-particlecloud-hypotheses`: cluster `/particle_cloud` during CHECKING
**Downgraded** (value medium → low) · configure · effort S
- **Verifier:** weights are uniform after resample (resample_interval 2), so shares must be particle counts. The HMI publishes `/initialpose` with σ 0.5 m / 15° (`adapter.py:989-990`) and recovery is off, so a wrong-aisle drop shows no mode in the right aisle. It can expose along-aisle aliasing only. Read-only CHECKING aid; never an integrity bound.

#### `amcl-persisted-initial-pose`: offer the last READY pose as a pre-filled `/initialpose`
**Keep.** configure · value medium · effort S
- **What:** closes "every boot needs an operator initial pose" without weakening the human gate.
- **Sources:** Humble `amcl_node.cpp`; `amcl.yaml:16-19`.
- **Sketch:** localization monitor writes `~/.amr/last_pose.json` atomically (tmp + fsync + rename) with map_id/revision/sha256 at throttled READY ticks and clean shutdown. HMI "use last pose" publishes it via the existing `adapter.set_initial_pose` path (identity checks); refuse on revision mismatch or age limit. Readiness still needs scan evidence + confirm. Wording must push the operator to check, e.g. "confirm the vehicle was not moved".
- **Verifier:** `save_pose_rate` is dead in Humble (period computed, never used); pose is written back to `initial_pose.*` only in `on_deactivate` and only with `set_initial_pose: true`. Remove or comment the 0.5 in `amcl.yaml`.

#### `nanoscan3-data-output-diagnostics`: scanner flags for localization explanations
**Downgraded** (value medium → low, effort S → M) · configure
- **What survives:** use the driver's `/diagnostics` contamination warning/error as a named reason for LOC_SCAN_MISMATCH (plan P1-12 already plans SCANNER_CONTAMINATED/SCANNER_ERROR from it); optional per-beam mask from `extended_scan`.
- **Verifier:** `status_overview` and `field_data` are services, not topics. ExtendedLaserScan has no glare field (it carries `reflektor_status[]`, `reflektor_median[]`, `intrusion[]`; `intrusion[]` is filled from the per-beam contamination bit). Glare, scan_number and device timestamp are only in `raw_data`, which is expensive to deserialise in rclpy. See `scn-diag-status-overview`.

#### `nav2-keepout-filter`: runtime KeepoutFilter from the revision's keepout mask
**Keep.** configure · value medium · effort M (was S) · installed nav2_costmap_2d / nav2_map_server 1.1.20
- **What:** keepout enforced in the controller's costmap, not only at route approval (`footprint.py:289`), so a drifting route hits RPP's collision check.
- **Sources:** docs.nav2.org keepout_filter; Humble `keepout_filter.cpp`, `costmap_filter_info_server.cpp`.
- **Sketch:** when the revision has `keepout.yaml`, launch `keepout_mask_server` (trinary mode, bundle's own thresholds) and `costmap_filter_info_server` (type 0) under `lifecycle_manager_navigation`; add `keepout_filter` to local_costmap. Sim mechanism test: a keepout cell is lethal in local_costmap. Executor stop code to explain a "blocked" result. No SpeedFilter.
- **Verifier:** humble KeepoutFilter handles mask_frame ≠ global frame via a TF lookup at TimePointZero (not the MessageFilter path). Two more lifecycle nodes lengthen startup on the N97.

#### `laser-filters-shadows`: ScanShadowsFilter + Speckle ahead of scan_gate
**Downgraded** (value low) · new · effort S · apt 2.0.9, not installed
- **Verifier:** no observed veiling/speckle problem; an extra node adds a DDS hop and copy of 1152-beam scans at 17 Hz on a thermally limited CPU; shadow removal near the mesh cage could drop the see-through returns scan_consistency reasons about. If ever needed, a few numpy lines after the gate.

### 2.6 supervisor-ops

#### `systemd-can0-return-and-startlimit`: bring amr.service back when can0 returns
**Keep.** configure · value high · effort S · systemd 249
- **What:** with `BindsTo=…can0.device` the unit stops cleanly on re-enumeration, `Restart=on-failure` does not fire, and nothing restarts it. Start limits also apply to manual starts, so the web Restart button fails for up to 60 s after the third failure.
- **Sources:** local `man systemd.unit`/`systemd.device` (249); freedesktop.org systemd.unit/device; host `70-canable.rules`, `canable@.service`.
- **Target:** `amr_ws/deploy/amr.service`, `amr-web.sudoers`, `install.sh`, `validate.sh`.
- **Sketch:** keep `BindsTo=`; add `After=canable@can0.service` and `[Install] WantedBy=multi-user.target canable@can0.service`. Sudoers: exactly `… NOPASSWD: /usr/bin/systemctl reset-failed amr.service`; web Restart runs reset-failed then restart (fixed argv). `Upholds=` is the wrong tool (restarts after a deliberate stop). The WantedBy takes effect only at the witnessed `systemctl enable` cutover.
- **Risks:** a restart boots to IDLE/LINE with the lease inhibited; motion still needs AUTO + fresh Start. A flapping adapter is capped by StartLimitBurst 3/60 s.
- **Verifier:** this is plan P1-4, with a better target (canable's ExecStartPost sets the link up before "active"; the device unit appears before `ip link set up`). `canable@.service` and `70-canable.rules` are host-only; validate.sh cannot check them until versioned (plan P2-5). The start-limit refusal clears itself 60 s after the first counted start.

#### `systemd-envfile-dropin-precedence`: data-volume drop-in overridden by amr.env
**Keep.** configure · value low (was medium) · effort S
- **What:** `EnvironmentFile=` beats `Environment=`, so the drop-in's `AMR_STATE_DIR`/`AMR_MAPS_DIR` never apply. Fix with a second `EnvironmentFile=` in the drop-in (read later, wins).
- **Sources:** local `man systemd.exec` (249) EnvironmentFile.
- **Sketch:** drop-in = `RequiresMountsFor=/data/amr` + `EnvironmentFile=…/amr-data-volume.env`; validate.sh checks the resolved `AMR_STATE_DIR`; `tools/run_log.sh` uses `$AMR_STATE_DIR`.
- **Verifier:** latent: the drop-in is not installed and `/data/amr` not mounted; the planned `~/.amr` symlinks would mask it. Fix before the W8 volume.

#### `sdnotify-extend-timeout-status-executor-watchdog`: unused sd_notify features
**Downgraded** (value high → medium) · configure · effort S
- **What survives:** `STATUS=` on every ModeState change (e.g. `NAVIGATION gen 7 lease=inhibited`) and rate-limiting pings via the unused `interval_s` (`sdnotify.py:26`).
- **Verifier:** the executor-heartbeat watchdog is plan P1-5; the stop margin is plan P2-7 (parallel, shorter stop), which makes EXTEND_TIMEOUT_USEC redundant (it can only extend). NotifyAccess=main is correct (`exec python3`). Land `WatchdogSignal=SIGINT` before gating the watchdog on the executor, or a watchdog kill SIGKILLs drive_node and latches 8130h.

#### `uptime-boot-id-and-service-result`: classify unclean shutdowns by boot_id and `$SERVICE_RESULT`
**Keep.** augment · value medium · effort S
- **What:** `/proc/sys/kernel/random/boot_id` in the marker gives a clock-independent power-cut vs crash test (today `btime` vs wall-clock `written_at` can be fooled by RTC error or an NTP step). `ExecStopPost` receives `$SERVICE_RESULT`/`$EXIT_CODE`/`$EXIT_STATUS` (watchdog, signal, core-dump, timeout).
- **Sources:** docs.kernel.org sysctl/kernel (boot_id); local `man systemd.exec` (249); `uptime.py:63-71,124`.
- **Sketch:** `write_marker()` adds boot_id (never raises); `classify()`: different → POWER_LOSS, same → SERVICE_CRASH, missing → btime fallback. `ExecStopPost=-…` writes `last_stop.json` atomically as User=; supervisor folds it into the SERVICE_CRASH sentence. Pure and testable with injected ids. Complements plan P1-4's rewording.

#### `launch-shutdown-timeouts-aligned`: align launch's sigterm/sigkill ladder with the Group window
**Downgraded** (value medium → low) · configure · effort S
- **What survives:** if wanted, pass `sigterm_timeout:=N sigkill_timeout:=M` on the `ros2 launch` argv from the Group (launch configs are global) rather than editing every file. Base values must be measured against drive_node's disarm time on the vehicle.
- **Verifier:** facts verified in installed `execute_local.py` (5 s/5 s defaults, noninteractive SIGINT to direct children), but the overlap is mostly harmless. `required()` for lifecycle managers is already P1-5. `respawn_max_retries` is Iron+.

#### `nav2-lifecycle-health-after-commit`: poll `is_active` after COMMIT
**Keep.** configure · value high · effort S
- **What:** the lifecycle manager bonds every managed Nav2 node (C++ bond heartbeats from the node's executor, so it sees a hung-but-alive node) and hard-resets on a miss. The supervisor never notices after COMMIT today.
- **Sources:** Humble `lifecycle_manager.cpp`; strings of installed `libnav2_lifecycle_manager_core.so` 1.1.20 ("Nav2 Health", "IS DOWN after not receiving a heartbeat").
- **Target:** `supervisor_node.py` (clients already exist at `:233-236`, used only at the lm:check stage), `readiness.py`.
- **Sketch:** in NAVIGATION, every 2 s `call_async` both `is_active` Triggers of the current generation; two consecutive false/timeout → `_fail_active('LAYER_INACTIVE')`, which only inhibits and explains; recovery is operator Recover → new generation. Pure predicate `layer_health(now, last_true, last_reply)`. Pair with `attempt_respawn_reconnection: false` (`lifecycle-event-bringup`).
- **Risks:** `is_active == true` must never grant anything.
- **Verifier:** detection latency is bounded by `bond_timeout` 20 s (kept for N97 startup). Mapping needs a separate freshness path (slam_toolbox is not lifecycle-managed in Humble).

#### `diagnostic-aggregator-health-tree`: diagnostic_updater + aggregator
**Downgraded** (value medium → low) · new · effort M · installed 4.0.7, unused
- **Verifier:** plan P1-1 already chose a typed `DeviceHealth.msg` + pure `agv_core/health.py`; an aggregator adds a seventh string-based channel against "codes are message fields" and does no common-cause correlation. Remaining value: Foxglove's Diagnostics panel for engineers.

#### `rosbag2-snapshot-blackbox`: always-on snapshot recorder dumped on FAULT
**Keep.** new · value high · effort M · rosbag2 0.15.17 + mcap installed
- Merged with `rosbag2-snapshot-mcap` (hmi) and ecosystem `rosbag2-snapshot-blackbox`; see §2.8 for the full entry.
- **Verifier (this area):** in Humble, `take_snapshot()` splits to a new file but `metadata.yaml` is written only in `close()`; reindex or read the `.mcap` directly. RAM ≈ 2 × max-cache-size. Measure subscription CPU (tf, wheel_states) with pidstat before default-on. With `--node-name amr_blackbox` the service is `/amr_blackbox/snapshot`. Optional role, never `required()`.

#### `rosbag2-record-split-preset-storagefilter`: unused rosbag2 options in run_log/bag_report
**Downgraded** (value medium → low) · configure · effort S
- **What survives:** `-d` split for long runs and `StorageFilter(topics=[…])` streaming reads in `bag_report.py`.
- **Verifier:** `run_log.sh` already records `-s mcap -e … --include-hidden-topics`. `zstd_fast` adds recording CPU during the very runs used to measure CPU/temperature; record `fastwrite` and convert afterwards if compression is wanted.

#### `ros-log-bounding`: bound `~/.ros/log`
**Keep.** configure · value medium · effort S · Humble rcl/launch + systemd 249
- **What:** `--disable-external-lib-logs` (present in Humble rcl) on nodes whose stdout already reaches the role log, and age-based `systemd-tmpfiles` pruning for log and bag directories only. `~/.ros/log` holds 7628 entries / 59 MB today; `launch.log` has no rotation.
- **Sources:** docs.ros.org Humble logging; strings of `librcl.so`; launch `logging/__init__.py:47-61`; tmpfiles.d man page.
- **Sketch:** new `amr_ws/deploy/tmpfiles-amr.conf` (`e <ros_log> - - - 7d`, runs 30d, blackbox 14d) installed by install.sh; extend `logs.sweep_generation_files()` to `loc_map_gen<N>.{pgm,yaml}`; add ros_log to `disk.py`. Never target maps or operation journals.
- **Verifier:** `ROS_LOG_DIR=$AMR_STATE_DIR/ros_log` is already plan P2-7. `/data/amr` does not exist yet; tmpfiles paths follow the effective `AMR_STATE_DIR` (today `~/.amr`). Installing a tmpfiles conf enables/starts nothing.

#### `events-transient-local-and-journal-fields`: TRANSIENT_LOCAL `/amr/events` + journald fields
**Downgraded** (value medium → low, effort S → M) · configure
- **Verifier:** `/amr/events` has 8 publishers (supervisor, drive_node, panel_node, cmd_mux, line_follow, route_executor, mapping_session, localization_monitor); a TRANSIENT_LOCAL subscriber does not match VOLATILE publishers, so all must change, including the safety-listed mux. Event.seq is per source and resets; dedup needs a msg change. Persistence while the web is down is plan P1-15. Structured `AMR_CODE` journal fields remain a modest optional extra.

#### `cyclone-loopback-multicast-buffers`: multicast on lo, larger receive buffer
**Downgraded** (value medium → low) · configure · effort S
- **What survives:** `SocketReceiveBufferSize` + `net.core.rmem_max` (now 212992), only after evidence of receive drops of large fragmented samples.
- **Verifier:** unicast discovery over lo is a documented deliberate choice (README, XML comment); SPDP at ~30 s is negligible; the 120-participant cap is nowhere near. Lo multicast changes discovery for every participant and needs a boot-ordered oneshot and a witnessed vehicle check.

### 2.7 gating-motion

#### `steady-clock-freshness`: monotonic receive stamps and tick in the mux; negative age = stale
**Keep.** augment · value high · effort S · rclpy STEADY_TIME, chrony
- **What:** a wall-clock step can no longer make a stale lease/permit/command look fresh. This is plan P0-7.
- **Sources:** rclpy `node.py:1486` (create_timer clock), `clock.py:149,229`; chrony.conf makestep.
- **Target:** `cmd_mux_kinematics_node.py:282-283` (`_now` on ROS clock), `gating.py:254-255` (`_fresh` accepts negative age); plan scope also `panel_node.py:105`, `line_follow_node.py:279`, `route_executor_node.py:344`, `supervisor_node.py:233`.
- **Sketch:** steady clock for `_now()` and the 50 Hz timer; `0 <= now - t <= limit`; optional jump callback emitting CLOCK_JUMP. Contract test that mux `_now` is monotonic; new test "future stamp → SOURCE_TIMED_OUT / zero".
- **Failure mode / recovery (gating.py is listed):** a backward step makes a sample read stale → zero at once; recovery is the next fresh message.
- **Verifier:** chrony 4.2 is installed with `makestep 1 3` already (`/etc/chrony/chrony.conf:57`), timesyncd removed; only the versioned drop-in and a validate.sh check are missing. `use_sim_time` is not used anywhere, so the sim risk does not apply.

#### `blvr-tpdo3-hwto-speeddev`: 60FDh (HWTO bit and R-OUT functions) on a TPDO
**Keep.** new · value high · effort M · Humble: n/a
- **What:** per-wheel read-only evidence that STO reached the drive (60FDh bit 3, fixed), plus default R-OUT functions (TRQ-LMTD, STOP_R, FREE_R, ALM-A, VA). Answers plan M2 without wiring, purchase or FX3 revalidation.
- **Sources:** `blvr_canopen.md` p.113 (60FDh UINT32 ro, PDO), p.90-91, p.80/86 (1802h/1A02h), p.14; `guard.py:99-116`.
- **Target:** `canopen.py` `tpdo_configuration_steps`, `drive_node.py` decode, `DriveStatus.msg` (colcon build), Drives reason codes (DRIVE_HWTO, WHEEL_BLOCKED as fields).
- **Sketch:** use the TPDO3 split in §0 (60FDh + 407Bh, type FFh with inhibit set: type 255 also transmits on change, TPDO2 measured ~1200 f/s without inhibit). Test that the steps pass `guard.check`. Mapping is volatile, re-written at every arm.
- **Risks:** explanation only; never re-enable motion from it.
- **Verifier:** 4075h/406Bh/406Ch are already polled by the SDO monitor slot (`canmon.py:55`), so PDO for them is optional. Drop the proposed `tracking.py` that zeroes on command-vs-measured mismatch: it contradicts plan P2-2 "skip commanded-vs-actual (false trips on ramps)"; warn-only per M9 at most. R-OUT assignments are 4xxxh parameters, so bits 16-31 carry defaults only if nobody changed them: read 60FDh by SDO on the vehicle first. Whether TPDOs keep flowing under HWTO is plan P1-14 (unconfirmed). 4075h meaning in pv mode is ambiguous.

#### `odom-twist-from-606c`: odometry twist from 606Ch
**Keep.** augment · value medium · effort S
- **What:** `WheelStates` already carries `left/right_vel_rad_s` from 606Ch (`drive_node.py:786-787`), but `diff_drive_odom_node.py:89-95` differentiates 6064h over a header dt that is the pair-complete publish time, so dt jitter feeds vx/vyaw. Use the 606Ch velocities for twist; keep 6064h deltas for pose.
- **Sources:** `canopen.py:10-21,72-77,157`; `blvr_canopen.md` p.38; Humble diff_drive_controller (velocity-feedback path).
- **Sketch:** a few lines in the odom node behind a parameter switch; consolidate the duplicate `WHEEL_RAD_S_PER_MOTOR_RPM` (`cmd_mux_kinematics_node.py:72`, `commissioning.py:72`) into `diff_drive.py`.
- **Verifier:** measure 606Ch lag against the 6064h derivative on a logged run first. The 6064h-vs-606Ch plausibility check is plan P2-2 (DRIVE_FEEDBACK_IMPLAUSIBLE); its gap bridge (same-epoch count delta bounded by MAX_RPM × gap, gap < 0.5 s) wins over the candidate's 606Ch integration.

#### `rl-ekf-unused-params`: vy = 0 fusion, dynamic process noise, reset_on_time_jump, lower rate
**Downgraded** (value medium → low) · configure · effort S
- **What survives:** fuse vy = 0 (start variance 1e-3) and `dynamic_process_noise_covariance: true`, tried together with odometry calibration and settled on logs.
- **Verifier:** options exist in 3.5.4. The "~40 % less EKF CPU" is unsubstantiated. `route_executor_node.py:308` and `survey_move_node.py:80` also consume `/odometry/filtered`, and SLAM/AMCL need the TF, so check before lowering frequency. `reset_on_time_jump` matters little after P0-7. `use_control` needs a stamped body twist the mux does not publish.

#### `odom-calibration-umbmark-scanref`: odometry calibration from commissioning evidence
**Keep.** new · value high · effort M · method only (robot_calibration Humble 0.8.3, Apache-2.0, is not run)
- **What:** proposed profile values for effective track, left/right diameter ratio (UMBmark CW/CCW square) and gyro scale (wall-referenced pivots in `/scan`). `blindrun.py` says outright that nothing corrects towards a physical reference; the corrupt boiacca-map-1 rev1 survey (20° slips) makes yaw scale directly valuable.
- **Sources:** Borenstein & Feng, IEEE T-RA 12 (1996); robot_calibration README (base_calibration_node); ros2_controllers diff_drive_controller multipliers.
- **Target:** new pure `agv_core/odocal.py` + `tests/test_odocal.py`; `commissioning_node.py` grabs one `/scan` at settled pivots; profile gets e.g. `wheel_ratio_rl` (schema + validation + refusal test).
- **Sketch:** the square = 8 straights + 8 pivots as blind-run plans, one panel Start per segment. Results go to a report; a human edits the profile.
- **Risks:** never run robot_calibration's node (it publishes its own velocity commands, bypassing panel-owned entry). Never auto-write the profile. Caps unaffected.
- **Verifier:** scanner sees ±95° only, so wall-referenced pivots should be full 360° turns (wall angle before and after), or small pivots that keep the wall in view. tracked-plan-3 M6 sets only a k_odo scale.

#### `nanoscan3-dataoutput-fields`: OutputPaths `is_valid`, active monitoring case, status
**Downgraded** (value high → medium) · configure · effort S
- **What survives:** treat `!is_valid[i]` on a configured path as FIELD_UNKNOWN (fails toward zero; plan phase 2 / P2-4); report `active_monitoring_case` without gating on it until echoed on the vehicle. Use the `status_overview` service at a low poll rate for device state. See `scn-outputpaths-valid-safe` for the gating entry.
- **Verifier:** `active_monitoring_case` = ApplicationOutputs monitoring-case vector `.at(0)`, and 0 when the flags vector is empty (upstream issue #46 workaround); gating on it could hold AUTO permanently. Reject the `raw_data` subscriber (1152 ScanPoints per message in rclpy on an N97 that already needed skip:1 for heat). Installed: driver 1.0.5, interfaces 1.0.1, base 1.0.4.

#### `fx3-gateway-readonly`: FX0-GMOD Modbus TCP gateway
**Downgraded** (value medium → low) · new · effort L
- **Verifier:** purchase + Flexi Soft change + re-validation; the FX3 CPU model (which decides gateway support) is not recorded in the repo. Cheaper paths exist: Q3 (its destination is open; DI08 is the Manual Arm switch, 2026-10-28), Q4 spare (`fx3-spare-q4-status-bit`), and 60FDh HWTO. Only if per-function FX3 logic state, module faults or a config checksum are wanted later; read-only, network-input set unmapped.

#### `rt-sched-motion-nodes`: SCHED_FIFO / affinity / gc.freeze for drive_node and mux
**Downgraded** (value medium → low) · augment · effort S
- **What survives:** `gc.freeze()` after init (cheap, safe). Otherwise follow plan P2-5/M5: measure with the P0-6 overrun counter, then Nice/CPUSchedulingPolicy at unit level or per-thread for the bus thread.
- **Verifier:** `sched_setscheduler(0, …)` affects only the calling thread; threads rclpy/DDS created earlier keep SCHED_OTHER. A FIFO Python thread waiting on a GIL held by a SCHED_OTHER thread is priority inversion. Kernel is generic 6.8, not PREEMPT_RT.

#### `pendant-release-before-use`: anti-tie-down for pendant levels
**Downgraded** (value medium) · augment · effort S · blocked on user sign-off Q2
- **Verifier:** this is plan P0-10, which places the logic in PanelAdapter (`amr_base/panel_io.py`) with `gating.py` and DebouncedLevels unchanged, including the coincidence-guard MANUAL entry and the tests (replace `test_panel_io.py:142`). The candidate's placement in `agv_core/panel.py` DebouncedLevels contradicts that design and the documented contract (`panel.py:146-148`). Behaviour itself is sound (removes motion only). The decision is the user's.

### 2.8 hmi-tooling

#### `foxglove-bridge-readonly-lockdown`: read-only, whitelisted, single-thread Foxglove
**Keep.** configure · value high · effort S · apt foxglove_bridge 3.5.0 (all args exist in the installed launch file)
- Merged with ecosystem `foxglove-bridge-readonly`.
- **What:** closes the path where any LAN client publishes `/amr/manual_command`, calls `/amr/mode/request`, `/amr/commissioning/plan`, `/amr/supervisor/recover`, sets Nav2 RPP dynamic parameters and sets sick_safetyscanners2 parameters (its callback sends a CoLa2 `changeSensorSettings`). The WebSocket protocol has no per-client auth; `device_token` is only for the cloud gateway (`remote_access` defaults false). The bridge subscribes only when a client subscribes.
- **Sources:** `/opt/ros/humble/share/foxglove_bridge/launch/foxglove_bridge_launch.xml`; foxglove-sdk ros README; strings of `libfoxglove_bridge_component.so`.
- **Target:** `supervisor_node.py:1013-1018` argv; `launch_helpers.foxglove()`.
- **Sketch (supervisor argv):** `capabilities:=[clientPublish,connectionGraph,assets]`, `client_topic_whitelist:=['^/initialpose$']`, `service_whitelist:=['(?!)']`, `param_whitelist:=['(?!)']`, `topic_whitelist` = map, scan, tf, tf_static, robot_description, `/amr/.*_ui`, `^/wheel_states_ui$`, `^/amr/route_markers$`, route preview, diagnostics, `/odometry/filtered`, `/amcl_pose`, `/plan`; `num_threads:=1`, `max_qos_depth:=2..5`, `sysinfo:=false`, `remote_access:=false`, `publish_client_count:=true`. Use the `'(?!)'` never-match idiom (empty lists do not round-trip). Launch-args unit test asserting the lists. For write access on the bench: a second instance on `address:=127.0.0.1` reached by `ssh -L` (SSH keys become the auth).
- **Risks:** removes a bypass; nothing added to the safety path. `send_buffer_limit` 10 MB can drop a very large `/map` for a slow client.
- **Verifier:** keep `clientPublish` limited to `^/initialpose$`: the runbook (`tape-localization-runbook.md:204`, `amr_ws/README.md:63`) uses Foxglove "2D Pose Estimate", and the standalone `nav.launch.py`/`mapping.launch.py` flows have no supervisor, so Foxglove is their only initial-pose path. Regex must add `^/wheel_states_ui$` and `^/amr/route_markers$`. Installed default `max_qos_depth` is 10 (README says 25); depth 1 risks losing a second static broadcaster. The mux speed parameters are not writable at runtime; the concrete parameter hazards are RPP and the sick driver.

#### `waitress-wsgi`: waitress instead of Werkzeug's dev server
**Keep.** replace · value high · effort S · apt `python3-waitress` 1.4.4 (Jammy)
- **What:** in-process thread-pool WSGI (no fork, works with rclpy), HTTP/1.1 keep-alive, main thread does all socket I/O so a slow tablet cannot pin a worker.
- **Sources:** waitress docs (arguments, design); apt-cache policy.
- **Target:** `amr_web/web_node.py:33`; `package.xml` exec_depend.
- **Sketch:** `serve(app, host='0.0.0.0', port=5001, threads=12, channel_timeout=30, ident=None)` on the main thread, Spinner unchanged; keep connection_limit at the default 100. Cut `adapter._call` timeouts below the browser's 8 s REQUEST_TIMEOUT_MS (mandatory with a fixed pool). demo_server may stay on Werkzeug.
- **Risks:** pool exhaustion behind 30 s service calls would queue jog refreshes; jog stays fail-safe (ticket and CMD_S expire, mux zeroes), held-not-latched unchanged. No WebSocket upgrades under waitress.
- **Verifier:** Werkzeug 3.1.8 `serving.py` always sends `Connection: close`, so every jog refresh pays a handshake over Wi-Fi. Prefer apt 1.4.4 over pip.

#### `sse-telemetry-push`: Server-Sent Events for state/alarms/pose
**Downgraded** (value medium → low) · augment · effort M
- **What survives:** a ~200 ms memo of `adapter.state()` and alarm rows behind one lock (removes `/api/alarms` calling `state()` a second time and per-tablet recomputation), and a lock on StandingTracker (`_since` race). Revisit push only if web CPU is measured material with 2+ tablets.
- **Verifier:** each stream pins a waitress worker; needs hub thread, 503 cap, fallback, per-frame freshness. Flask-SocketIO/flask-sock are not viable under waitress on Jammy.

#### `rosbag2-snapshot-mcap`: always-armed snapshot recorder in the report zip
**Keep.** new · value high · effort M · ros-humble-rosbag2 0.15.17, storage-mcap, compression-zstd installed
- Merged with supervisor-ops and ecosystem `rosbag2-snapshot-blackbox`.
- **What:** the last N MB of low-rate control topics always in RAM (serialized, no deserialization), written to MCAP only on a trigger. Evidence for every unexplained stop with no continuous disk writes.
- **Sources:** local `ros2 bag record --help`; `rosbag2_interfaces/srv/Snapshot.srv`; Humble recorder.cpp (`~/snapshot` only in snapshot mode); Humble rosbag2_cpp CHANGELOG 0.15.13 (#1842 backport).
- **Target:** new supervisor process group `blackbox` (allow-listed argv), trigger from `_fail_active` / stop-explanation path and the web report button; `reports.py` adds the newest file; reuse `run_log.sh`'s TOPICS as the base.
- **Sketch:** `ros2 bag record --snapshot-mode --max-cache-size <bytes> -s mcap --storage-preset-profile fastwrite --node-name amr_blackbox -o $AMR_STATE_DIR/blackbox/<boot> -e '<regex>' --include-hidden-topics`. Topics: `/amr/events`, mode_state, RunState, LineState, MuxState, lease/permit, mux in/out, `_ui` copies, `/output_paths`, `/diagnostics`. No `/map`, no `raw_data`. Record active map id/revision/sha256 in `state.json`. A pure trigger policy (which event codes dump) in agv_core. Prune by count/age (tmpfiles). Also fix `reports.py:102` to use `config.PROFILE_PATH_LOADED`.
- **Risks:** never a `required()` role; a dead recorder must not fault the vehicle. Snapshot trigger behind the role check (Foxglove services off). Read-only, no CAN/scanner/motion interaction.
- **Verifier:** 0.15.13+ writes each snapshot to a new file, so the SIGINT-and-restart dance is probably unnecessary: bench-check the footer, then drop it. Metadata only at exit (see §0). RAM ≈ 2 × cache (~100 MB at 40 MB, not 40-60 MB). `--node-name` avoids clashing with run_log's `/rosbag2_recorder`. `/scan` and `/amr/line_track` (100 Hz, most useful in LINE) need a CPU budget on the N97 before default-on; `run_log` excluded `/scan` deliberately. Cache is byte-bounded, not time-bounded: size it deliberately.

#### `lichtblick-offline-client-layout`: Lichtblick with a versioned default layout
**Keep.** augment · value medium · effort S (was M) · browser/desktop app, MPL-2.0
- **What:** records the engineer client (today "Foxglove app, client unrecorded") and versions a layout JSON (3D panel, Diagnostics, Plot of `_ui` topics, mode State Transitions).
- **Sources:** github lichtblick-suite/lichtblick (v1.30.0 2026-10-22; v1.29.1 CSP fix over the websocket bridge; Dockerfile default-layout placeholder).
- **Sketch:** install the prebuilt desktop app (.deb) on the engineering laptop; commit `amr-default-layout.json`. Serving the web bundle from the IPC's Flask is optional and not recommended. One bench check of bridge compatibility and `ds.url` query params.
- **Verifier:** releases ship prebuilt web tarballs and desktop installers; no Node 22 build needed.

#### `plotjuggler-mcap-analysis`: PlotJuggler on the laptop
**Downgraded** (value medium → low) · new · effort S · apt 3.17.2 + plotjuggler-ros 2.3.1
- **Verifier:** laptop-only, no vehicle cost, but overlaps `tools/bag_report.py` (CSV extraction) and depends on the snapshot bag. A convenience plus one layout XML.

#### `diagnostic-updater-ipc-health`: IPC health on `/diagnostics`
**Downgraded** (value medium → low) · configure · effort S
- **Verifier:** `state.json` already carries IPC temp and disk. The adapter subscribes `/diagnostics` itself (`adapter.py:295`), so its own statuses loop back. Tasks must refresh cached values off the lock or publish stale values as OK. Turning off bridge sysinfo belongs to the lockdown. See `ipc-throttle-telemetry` for the part worth doing.

#### `tf2-web-republisher-pose`: C++ TF republisher for the web pose
**Downgraded** (value medium → low) · replace · effort M · apt 1.0.0, not installed
- **Verifier:** goals run until cancelled with no timeout, thread per goal; the web's `os._exit(0)` path would orphan goals that publish forever; +15-20 MB. The larger Python cost is full `/scan` deserialization. The house pattern is a 5 Hz pose `_ui` topic from the localization side.

#### `zlib-rle-png`: vectorised filter column + `Z_RLE`
**Keep.** configure · value medium · effort S · stdlib + numpy
- **What:** `png.encode_gray`: `np.hstack` of a zero filter column, `zlib.compressobj(2, DEFLATED, 15, 9, Z_RLE)`. Measured on rev-boiacca-map-01 (2385×1565): 67-74 ms / 139 KB → 24-29 ms / 123 KB, byte-identical scanlines.
- **Sources:** Python 3.10 zlib docs; W3C PNG §9 filters; `png.py:18-24`.
- **Sketch:** plus an LRU-bounded (~4) cache of the encoded bundle PNG (`server.py:538`) and bounds on `_grids`/`_extras` (`:186/:199`), which are the larger part of the value. Existing round-trip tests cover correctness.

#### `eventlog-queue-writer`: EventLog I/O off the executor
**Downgraded** (value medium → low) · augment · effort S
- **What survives:** make `tail()` walk all rotated files up to the 300-event need (reload is capped at ~10 MB of history). Queue writer only if a disk stall is ever observed.
- **Verifier:** events are low-rate; appends are µs; only error-level fsyncs cost ms; the web is display-only. A writer thread complicates the W4 "errors forced to the platter" ordering.

#### `openpyxl-commissioning-export`: XLSX export of blind runs
**Downgraded** (value medium → low) · new · effort S · apt python3-openpyxl 3.0.9 not installed
- **What survives:** independent fixes: wrap `getmtime` at `commissioning_log.py:95` in `try/except OSError`, and add role checks to existing command endpoints. A stdlib CSV or an off-vehicle one-off xlsx covers the PV-vs-PP table.

#### `jsonschema-state-contract`: `/api/state` contract shared by both adapters
**Downgraded** (value medium) · augment · effort S
- **What survives:** a stdlib contract test: key-set/type diff between stub-fed `RosAdapter.state()` and `DemoAdapter().state()` (~10 keys missing in demo), plus `inspect.signature` comparison of the Adapter Protocol against DemoAdapter (catches `line_mission(name)` vs `(name, destination)` TypeError at `demo_server.py:819`). Drop the jsonschema dependency.

#### `jinja-gettext-indonesian`: Indonesian operator UI
**Downgraded** (value low) · new · effort M
- **Verifier:** sound (Jinja2 i18n + stdlib gettext; agv_core stays ROS/Flask-free) but not requested; longer strings threaten the no-scroll fit at UI scale `l`. Park until operators ask.

### 2.9 peripherals

#### `scn-sd-persistent-udp-output`: continuous UDP data output saved in Safety Designer
**Keep.** configure · value high · effort M (was S) · device setting by a human in SICK Safety Designer
- **What:** answers plan Q3. The driver's start-up write is CoLa2 method 176 "Configure data output": volatile RAM state, not part of the safety configuration, logged in the scanner message history. After any scanner power cycle the scanner falls back to the data output saved in Safety Designer; if that is deactivated, UDP stops for good (driver does not reconnect: upstream issue #72, maintainer reply 2026-06-24). If the saved channel is "continuous to 192.168.3.2:6060" with matching blocks and ±95°, UDP returns to the driver's still-bound socket by itself.
- **Sources:** SICK TI 8022708 (1W29, 2026-05-26) §4.2.1 p.10-11, §4.2.2 NOTE p.11, §6.3.2.2 p.62 (method index 176), §6.3.1.4 p.56-59; `sick_safetyscanners_base` `ChangeCommSettingsCommand.cpp` (0x00b0).
- **Target:** Safety Designer project; `nanoscan3.yaml` comments; commissioning record.
- **Sketch:** channel 1: continuous UDP to 192.168.3.2:6060; blocks Device status, Data output config, Measurement data, Application data (no Object detection, see `scn-drop-intrusion-block`); −95..+95°. Record with TI page references. Essential if the scanner's 24 V is switched by the E-stop chain (open plan Q3 bullet): then every E-stop power-cycles the scanner.
- **Risks:** a configuration transfer changes the overall checksum and needs the documented verify/re-validation step for the PL d file, even though data output is non-safety. Software writes nothing new.
- **Verifier:** the saved channel configuration (TI index 177, p.57) includes `u16PublishingFreq`, so Safety Designer may be able to store "every 2nd scan": check rather than assume ~34 Hz after a power cycle. The driver never re-sends on its own, so data stays at the saved settings until restart. Re-pin the checksum if `scn-field-checksum-crosscheck` lands. Effort M: safety-responsible person, transfer, verify step.

#### `scn-param-reinit`: re-send the driver's volatile settings by a parameter set
**Downgraded** (value high → medium) · augment · effort S
- **What survives:** an optional fast path inside plan P1-12's pure `scanner_watch`: on silence with the scanner answering, a plain `rcl_interfaces/srv/SetParameters` client on `/sick_safetyscanners2_node/set_parameters` sets `channel_enabled=true`, which re-sends method 176 over a fresh session. Back off (1 per 5 s, give up after 3, then exit-and-respawn). Never used to clear a stop.
- **Verifier:** mechanism confirmed in 1.0.5 source, but the gain over P1-12's exit-and-respawn is ~5 s, small next to scanner boot time, and moot if `scn-sd-persistent-udp-output` is done. Humble rclpy has no `AsyncParametersClient`. A TCP exception in the callback while the scanner boots crashes the node (not "may"), which lands in respawn anyway. "~100 ms resume" unverified.

#### `scn-diag-status-overview`: driver `State` diagnostics and `status_overview` as stop explanations
**Keep.** configure · value high · effort S · installed driver 1.0.5, services/diagnostics unused
- **What:** contamination warning/error, device and application error, run mode and monitoring case are already published on `/diagnostics` (hardware_id = sensor IP). `status_overview` adds `config_state` (5 = Verified, 3 = Not verified) and an error code whose class gives the recovery action. All CoLa2 reads.
- **Sources:** SICKAG `SickSafetyscanners.cpp` sensorDiagnostics; installed `StatusOverview.srv`; TI 8022708 §6.3.1.3.1 p.47-49, §6.1 Table 4 p.21.
- **Target:** new pure `scanner_health.py` mapping (DiagnosticStatus key/values, StatusOverview) → enumerated codes in plan P1-1's `DeviceHealth` fields; web adapter (`adapter.py:638` already stores every `/diagnostics` status by name); readiness.
- **Sketch:** parse driver strings once in the pure module (pin key names with a recorded DiagnosticArray); call `status_overview` once at readiness and on a level change. Operator text e.g. "Lidar window dirty: clean cover, then Reset". May only add refusals (e.g. refuse AUTO Start when config_state ≠ Verified).
- **Verifier:** `State` goes STALE only before the first packet; after data loss it keeps the last-known values, so it is not a silence signal and the HMI must gate it on scan age. Silence shows in the driver's separate frequency/timestamp status for `/scan`. Checksums are read once at driver start. Only SCANNER_SILENT/STALE exist today; P1-12 intends SCANNER_CONTAMINATED/ERROR but is unbuilt.

#### `scn-field-checksum-crosscheck`: start-up cross-check of scanner_fields.yaml
**Downgraded** (value medium) · augment · effort M
- **What survives:** pin the overall configuration checksum in the profile (`lidar.config_checksum`, schema + refusal test, byte order reversed vs Safety Designer display per TI footnote 5) and refuse AUTO Start on mismatch. Field-geometry matching is a later, bench-checked step.
- **Verifier:** `FieldData.srv` gives no field-index → output-path mapping; no ConfigMetadata service exists; the checksum is reachable only as the diagnostics string "Overall checksum" (%08X). `scanner_fields.py` is listed: add a test; failure mode = false mismatch blocks AUTO; recovery = re-pin after a verified re-transfer.

#### `scn-outputpaths-valid-safe`: honour `is_valid` and show the active case
**Keep.** configure · value medium · effort S · installed message
- **What:** `is_valid[i] == False` means the path bit is not trustworthy: treat as UNKNOWN (no AUTO resume, most restrictive scale), like a stale message. Show the active monitoring case on the HMI.
- **Sources:** TI 8022708 §6.1 Table 9 p.26; installed `OutputPaths.msg`; `MessageCreator::createOutputPathsMsg`.
- **Target:** `cmd_mux_kinematics_node.py` `_on_output_paths` (L407-411), `gating.Field`, `scanner_fields.py`; plan P2-4, P1-13.
- **Sketch:** `gating.Field(now, status, valid)` in the pure module; tests "invalid path → no resume" and "unknown case → restrictive scale".
- **Failure mode / recovery (gating.py and mux are listed):** a spurious invalid holds AUTO at a stop; recovery is the operator Reset after a clear field.
- **Verifier:** do NOT make `is_safe[protective_index]` a load-time assertion: TI's "Safe: the respective cut-off path is safe" is ambiguous (safety-rated vs currently safe). Record `/output_paths` with the field clear and occupied first.

#### `scn-drop-intrusion-block`: disable the unused Object detection block
**Keep.** configure · value low · effort S
- **What:** saves ~3.55 KB per telegram (24 × (4 B + 1 bit/beam)), comparable to the ~4.6 KB measurement data. No consumer of `/extended_scan` or `/raw_data` exists. TI p.9/p.62 itself recommends deactivating Object detection.
- **Sketch:** `intrusion_data: false`; fix the yaml comment (field status comes from `application_io_data`); measure driver %CPU and `/output_paths` p99 inter-arrival before/after with bag_report.
- **Verifier:** ExtendedLaserScan's per-point `intrusion` comes from the scan point's contamination bit, not this block. Same volatile flag write the driver already makes. Deselect Object detection in the saved Safety Designer channel too, so both match.

#### `scn-monitoring-case-switching`: speed/segment-dependent field sets
**Downgraded** (value medium → low) · new · effort L · Safety Designer + FX3, humans only
- **Verifier:** a safety-configuration project (encoder speed monitoring in FX3, PL d re-validation), not a driver integration; nothing is blocked on it. Software side is covered by `scn-outputpaths-valid-safe` and P2-4. Core (3 universal I/O) vs Pro variant not recorded. Document as a later option.

#### `rfid-0072-heartbeat`: 0x0072 as the liveness heartbeat
**Keep.** augment · value high · effort S
- **What:** 0x0050 is "RFM_MODULE_INT (Initialize the device)" with no stated side effects, next to 0x0052 = factory reset. 0x0072 is a pure getter that `rfid.py` already sends at every connect while the reader streams (`rfid.py:564-566`). A 1 s 0x0072 heartbeat detects a wedged firmware (TCP keepalive cannot) and runs `param_mismatches()` continuously (catches a reader taken out of ACTIVE mode or factory-reset with the vendor tool).
- **Sources:** `tools/uhf-even/User Guide/UHF Even Reader user manual-EN.docx` §2.2.1, §2.2.2, 0x0072 table; `CFApi.h:401, :424`.
- **Target:** `agv_core/drivers/rfid.py` Heartbeat; profile `rfid.heartbeat_s` (0.0 today); unblocks plan P1-11/Q3.
- **Sketch:** heartbeat sends 0x0072 every `heartbeat_s`, one command per TCP segment; "answered" = any CRC-valid 0x0072 reply; reply feeds `parse_params → param_mismatches`; a `work_mode` mismatch raises plan P0-9's Start refusal. Bench first: `rfid_survey` reads/s with and without 1 Hz 0x0072 on a parked tag.
- **Verifier:** `_absorb` arms the Heartbeat only on CMD_ONLINE replies (`rfid.py:601-602`) and the docstring/logs name 0x0050: change both. `_on_params` logs info + a warn per mismatch on every reply (`:644-653`): make it edge-triggered. The connect-time 0x0072 and the first heartbeat must not go back-to-back in one loop pass.

#### `rfid-gen2-inventory-tuning`: Q, Session, FilterTime set with the vendor tool
**Downgraded** (value high → medium) · configure · effort S
- **What survives:** one more vendor-tool bench row (Q 4 → 1 → 0, S0 vs S1 at fixed geometry with `rfid_survey`), plus `expect_q_value`, `expect_session`, `expect_filter_time_s = 0` profile keys (schema + refusal tests) so drift warns. FilterTime must stay 0 (it would split one parked tag into repeat encounters against `tag_clear_s` 0.5 s); BufferEN (0x0074) must stay 0.
- **Verifier:** Q is an "initial Q" that the reader adapts, so with one tag the extra slots cost only ms. The recorded parked RSSI (−67..−77 dBm at 3-10 reads/s) points to RF margin (antenna, return loss, orientation, region), which is the agreed bench order. S0 is already right for repeated reads. Dual-target A/B (undocumented 0x0012/0x0013, vendor tool) is the likelier Gen2 lever. `parse_params` already decodes q_value/session/filter_time (`rfid.py:237-239`).

#### `rfid-site-epc-prefix`: reject foreign UHF tags
**Downgraded** (effort M → S) · augment · value medium
- **What survives:** a profile key for the expected EPC length (`rfid.epc_len = 4`, schema + refusal test). Station tags carry 4-byte EPCs; commercial bin/pallet/part tags are almost always 96-bit. Other lengths are counted and logged as foreign, never an encounter. A site prefix only if foreign 4-byte EPCs ever appear. Reader-side 0x0073 mask stays a human-only vendor-tool option.
- **Verifier:** today `parse_tag` takes the last 2 EPC bytes, so a foreign tag ending in a station id would be accepted. `rfid.ignore_tags` is per-id and empty.

#### `dio-pymodbus-retries-zero`: one timeout = one failed scan
**Downgraded** (value high → medium) · configure · effort S · pymodbus 3.15.0 (pip, lazy)
- **What survives:** land `retries=0` only together with plan P1-10's immediate reconnect; or use `retries=1` and count `response.retries` into the P1-10 drops counter (≤ 40 ms stretch, visible).
- **Verifier:** default `retries=3` resends up to 4× at 20 ms, so one read call can take 80 ms (two reads per scan). But `retries=0` alone today drops the client and waits `reconnect_period_s` 0.5 s, so panel freshness (> 0.2 s) lapses, forcing a re-baseline and losing authority. `reconnect_delay` is "Not used in the sync client".

#### `dio-fc03-combined-image`: DI and DO in one FC03 read
**Downgraded** (value medium → low) · augment · effort S
- **What survives (documentation):** name the module CK-TP5163 (not CK-EC5163, the EtherCAT series); evidence for `num_do = 12` (DO word bits 0-11) for P2-8; no watchdog or comm-loss safe state documented; bench-check whether the cascade OUT port drops the RFID reader when the module is unpowered (feeds plan P1-1 IO_ISLAND_LOST).
- **Sources:** CK-TP5163 Specifications Vr1.1 p.7-8 (FC 01/02/03/05/06/0F; holding 0x22 = DI word, 0x20 = DO word; default 192.168.1.30:502; on-chip cascading).
- **Verifier:** saves ~2 ms in a 50 ms scan and relies on an undocumented register gap (0x21). Keep per-coil FC05 writes, never FC06/FC10 word writes (would write unclaimed channels).

#### `dio-external-watchdog-relay`: retriggerable timer relay on the horn common
**Downgraded** (value low) · new · effort M
- **Verifier:** non-safety, no invariant conflict, but it fixes a nuisance (horn latched after PC death while motion is already stopped by heartbeat loss and STO). Park until the vendor answers (P2-8, Q5) and a latched horn is observed.

#### `diag-updater-python`: diagnostic_updater in rfid_node / panel_node, aggregator
**Downgraded** (value medium → low) · configure · effort S
- **What survives:** a `FrequencyStatus` in rfid_node and panel_node for the bag/engineer view. Skip the aggregator.
- **Verifier:** `adapter.py:638` already ingests raw `/diagnostics`; rate/staleness are planned as DeviceHealth fields (P1-1); no `package.xml` depends on diagnostic_updater today.

### 2.10 sim

#### `edt-sphere-trace-raycast`: distance-field sphere tracing for the scan synthesiser
**Downgraded** (value high → medium) · augment · effort S
- **What survives:** cheaper sim on the N97 (~20 % of a core → ~5 % at 10 Hz) and one raycaster for sim and `demo_server` (whose own copy treats "outside" as occupied). Same module as `dt-raymarch-field`.
- **Verifier:** re-run bench: 381 beams 25.6 → 5.3 ms, 1152 beams 49.1 → 7.7 ms, EDT build 5 ms; p99 diff 0.02 m but worst beams off by 2.8 m and 5.4 m and one inf/hit flip, so the fine-march finish on the same k·step grid and the equivalence test are mandatory. Use `DIST_MASK_PRECISE`, not mask 5 (overestimates → tunnelling). The cv2 the nodes import is pip opencv 5.0.0 from `~/.local`, shadowing apt 4.5.4: declare deliberately. Representativeness claims are overstated: scan_gate caps consumers at 10 Hz and AMCL uses 180 beams; sim tests check mechanisms only.

#### `canopen-localnode-vcan-emulator`: wire-level CiA 402 + MLS emulator on vcan0
**Downgraded** (value high → medium) · new · effort L · **invariant conflict as proposed**
- **What survives:** process-level integration of the real drive_node against python-canopen LocalNode slaves on vcan0, after two hard fixes.
- **Verifier:** the "fail-safe if a vcan profile reaches the vehicle" claim is wrong. `verify_drivers.py:open_bus` (`:140-168`) falls back to slcan on any auto-discovered CANable when the named socketcan channel is not up. This PC is the vehicle PC with the CANable plugged in, so a sim drive_node with channel `vcan0` and vcan down opens the real bus, under fake_panel AUTO+Start: a break of "panel owns entry into motion" and of domain separation. Prerequisites: `open_bus` must refuse the slcan fallback for any `vcan*` channel, and drive_node must refuse a non-vehicle domain unless the opened bus is `socketcan:vcan*`; both with tests (launch safety layering). Frame-level FakeBus tests (`test_canopen.py`, R04-R07, `test_pp_drivelink`, `test_mls_track`, `test_mls_imu`) already cover most sequencing. The BLV-R model is not authoritative. The ownerlock is keyed `can`, so it cannot run while amr.service holds can0 (intended).

#### `pymodbus-dio-rfid-emulators`: Modbus DIO emulator + RFID wire emulator
**Downgraded** (value high → medium) · augment · effort M
- **What survives:** the RFID wire emulator (reuse `rfid.command`/`crc16` so framing cannot drift), because rfid_node has no sim at all. Bind 127.0.0.1 only, never under `real:=true`, code in amr_sim.
- **Verifier:** DIO/panel already have offline coverage (`tests/test_dio.py`, `test_panel_io.py`); plan P3-2 already chose ROS-level fakes (fake_panel stop/valid=false hooks, a fake_rfid publisher). "Tracked jobs end to end" is false: `tape_synth` is not launched anywhere and emits no markers, LCP1/3 or branches.

#### `fake-output-paths-from-field-geometry`: `/output_paths` computed from scan vs field rectangles (sim only)
**Keep.** new · value high · effort S · installed `sick_safetyscanners2_interfaces`
- **What:** sim can exercise protective stop, warning_2 decel stop with `stop_m`, warning_1 ×0.5 and resume after a clear field, through the real mux and executor, with `/sim/add_obstacle`. Today sim never publishes `/output_paths` and injects `field_source=assume_clear` (plan line 80).
- **Sources:** installed `OutputPaths.msg`; `scanner_fields.yaml`; `gating.py:380-450`; `line_layer.launch.py:91-93`.
- **Target:** new `amr_sim/fake_output_paths_node.py` + pure `amr_sim/field_occupancy.py` (point-in-rect in scanner frame, N-beam/N-sample debounce for 0.01 m range noise); loader shared with `scanner_fields.load()`.
- **Sketch:** same node also carries plan P3-2's scripted overrides (drop / invalid / violate / clear), so FIELD_UNKNOWN and validity paths are covered. Opt-in parameter; do not replace `assume_clear` in the default unified suite.
- **Risks:** emulates the hardware decision in SIM only: launch only under `real:=false`, refuse domain 10 via `domains.refuse_vehicle_domain`, extend the `test_launch_layers.py:142` assertion, docstring forbids reuse as a vehicle field monitor. Mechanism check, not tolerance check.

#### `rosbag2-replay-regression`: replay recorded vehicle runs as regression fixtures
**Keep.** configure · value high · effort M · rosbag2 0.15.17, mcap, rosbag2_py installed
- **What:** real MLS noise, marker sequences, `/output_paths` flicker, wheel slip and panel edges replayed deterministically through the pure clock-fed modules (bag time as "now"), no ROS spin. Node variant: `ros2 bag play --clock` on a sim domain.
- **Sources:** rosbag2 humble README (player services); local `ros2 bag play --help`; `tools/run_log.sh:119-151`, `tools/bag_report.py`; `~/.amr/runs` (3 runs, 56 MB).
- **Sketch:** `tools/trim_bag.py` cuts 5-30 s fixtures into `amr_line/test/fixtures/*.mcap`; pure `replay.py` feeds MarkerDetector, field_view, hold-reason and staleness logic, tape health; assertions are mechanism-level (state sequence, markers decoded, hold reasons, zero on stale). Reuse bag_report's deserialisation helpers. Offline library suite untouched.
- **Risks:** replay only sensor topics, never command or lease topics; helper calls `refuse_vehicle_domain`. Override `use_sim_time` where yamls hard-code false (`amcl.yaml:9`, `nav2_params.yaml:9`). Re-cut fixtures after `amr_interfaces` changes.
- **Verifier:** open-loop replay is sound for detectors/classifiers, not for closed-loop tape-following trajectories. `run_log.sh` does not record `/scan`, so field-stop fixtures carry `/output_paths` without the scan.

#### `survey-flight-recorder-slam-replay`: record every survey; re-run slam_toolbox offline
**Downgraded** (value high, unchanged; approach corrected) · configure · effort M
- **What:** surveys leave no raw data today. Record `/scan`, `/wheel_states`, `/imu/data_raw`, ekf odometry, `/tf_static`, MappingState for every survey, so a bad survey (boiacca-map-1 rev1) is reproducible and the uncommitted angle-window and gyro-guard fixes can be validated without driving again.
- **Sketch:** mapping_session starts a plain continuous recorder (explicit topics, `nice -n 10`, failures are warnings) under the process supervisor; prune old revisions. Replay variant `replay_bag:=` on a sim domain with `use_sim_time`, `ros2 bag play --clock`, no seeking.
- **Verifier:** snapshot mode is the wrong tool: the cache is bounded (default 100 MiB), so a 10-20 min survey keeps only the last ~2-5 min and loses mid-survey slips. Filter slam_toolbox's own map→odom out of the replayed `/tf` or it fights the replayed SLAM. Async slam_toolbox drops scans when busy: use sync mode or `-r < 1` for comparisons. Measure CPU/heat during surveys (N97 already > 80 °C per `nanoscan3.yaml`).

#### `hypothesis-stateful-gating`: property-based and stateful tests for pure modules
**Keep.** augment · value high · effort S · apt `python3-hypothesis` 6.36.0 (Jammy), test_depend only
- **What:** random interleavings of ticks, lease renewals/expiries, generation changes, selector flips, Start edges, held manual streams and field samples, with invariants after every step: no nonzero output when the newest manual sample is > 0.2 s old, lease/permit > 0.3 s, or generation mismatched; no ramp extends a vanished command. Failures shrink to a minimal step sequence.
- **Sources:** hypothesis.readthedocs.io stateful; `gating.py:99-260, 380-560`; existing R02-R07 regression files show interleaving bugs did occur.
- **Sketch:** `amr_base/test/test_gating_properties.py` (`RuleBasedStateMachine`); similar small machines for WheelModel and TapePlant. `derandomize=True`, capped `max_examples`, thresholds from `gating.Params`/profile, not literals. Keep out of `tests/run_all.py` EXPECTED_CHECKS unless deliberately counted.
- **Verifier:** the "fresh Start edge under AUTO" rule lives in the panel/run/mode FSM path, not only in `gating.select`; model PanelState edge semantics (rising edge on exactly one message) to assert it.

#### `cgroup-scope-sim-tests`: contain each full-stack sim test in a `systemd-run --user --scope`
**Keep.** augment · value medium · effort S · systemd 249, user manager running
- **What:** layer groups `setsid`, so if the supervisor dies abruptly orphans escape the ppid/session ownership walk (`test_unified_sim.py:180-273`). A user scope holds every descendant; teardown becomes `systemctl --user stop` and "no descendants" becomes exact.
- **Sketch:** fixture starts the supervisor via `systemd-run --user --scope --unit amr-simtest-<domain>-<pid> --collect -p TimeoutStopSec=10`; `owned_pids()` reads the scope's `cgroup.procs` (path via `systemctl --user show -p ControlGroup`); keep the /proc walk as fallback when no user bus. Never `--system`.
- **Verifier:** lighter alternative in the same fixture: `prctl(PR_SET_CHILD_SUBREAPER)` on the pytest process. Value medium (needs an abnormal supervisor death).

#### `blvr-driver-simulation-mode`: BLV-R virtual-motor mode for bench HIL
**Downgraded** (value medium → low) · new · effort S · MEXE02 only
- **Verifier:** feature confirmed (function manual ch.9 §10 p.500-501; "Driver operation mode" reg 1022/1023, NET-ID 01FFh, update after power cycle). guard.py already denies all 4000h-4FFFh writes, so no guard change. The operator already bench-tests on blocks with real motors (RUNBOOK:587, 614). Forgetting to revert leaves odometry reporting motion with dead wheels. No readable CANopen object for a startup check (EDS has 403Fh, no 41FFh). STO behaviour in this mode is not stated locally.

### 2.11 ecosystem

#### `foxglove-bridge-readonly`
**Keep.** Merged into `foxglove-bridge-readonly-lockdown` (§2.8). This area's verifier added: amr.env sets `AMR_FOXGLOVE=true`, so the bridge runs in production; no firewall exists in `deploy/`; the strongest concrete hazard is the sick driver parameter path to a CoLa2 write.

#### `sick-driver-status-topics`: use the scanner status the driver already decodes
**Downgraded** (value high → medium) · configure · effort S
- **What survives:** consume the driver's `/diagnostics` State task (contamination, device/application error, monitoring case) plus `/output_paths` `is_valid`/`active_monitoring_case`, already subscribed. The agv_core classifier takes plain fields, not `sick_safetyscanners2_interfaces` types. `reset_required_cut_off_path` (only in `raw_data`) only if it proves necessary; it would map to `clears_by=start_button`, never auto-cleared.
- **Verifier:** overlaps plan P1-12. "Process every Nth raw_data" saves nothing: rclpy deserialises every delivered message (1152 ScanPoints at ~17 Hz).

#### `fx3-spare-q4-status-bit`: FX3 Q4 → DI09 as a read-only "E-stop/STO active" bit
**Keep.** new · value high · effort S (software; FX3 side by a human) · existing pymodbus DIO path
- **What:** a real non-safety copy of the FX3 logic state ("E-stop chain open or STO requested" / "reset required"), through Q3 into a free DI in DI09–DI0F (DI08 is the Manual Arm switch, 2026-10-28). Replaces the torque-loss guess (`job.py:398-402`).
- **Sources:** `documentation/electrical/01-schematic/io-mapping.md` §2 (Q3 → DI08 test pulses off; Q4 spare), §3 (DI09-DI0F unused, COM1); SICK Flexi Soft gateways manual im0078284 (stage 2 only).
- **Sketch:** a human sets Q4 in Flexi Soft Designer (test pulses off), wired to DI09 (COM1 group, like DI08); sheet 08/09 update through the electrical SKILL workflow. Profile DIO key + schema + refusal test; `config.py` cross-check that it differs from all panel/pendant channels; panel_io reads it with the usual freshness rule. A pure function uses it only to choose cause text and `clears_by` ("E-stop: release, reset, then Start").
- **Risks:** never "safe to move", never latch motion on it. FX3 project change = new checksum + re-verification, safety logic untouched.
- **Verifier:** DI08 is already Manual Arm, so Q4 → DI09 is the next free pair. Before any FX0-GMOD stage 2, confirm the fitted FX3 CPU accepts a gateway. Q4 must land on the COM1 group (DI09-DI0F); DI07 is COM0 (1P24) and a sourcing output would never read there (`fx3-q4-com1-group-constraint`).

#### `rosbag2-snapshot-blackbox`
**Keep.** Merged into `rosbag2-snapshot-mcap` (§2.8). This area's verifier added: it is the concrete mechanism for plan P2-10 (unbuilt); record the existing `_ui` copies (no decimated wheel_states copy exists).

#### `systemd-watchdog-replug-unclean-marker`: iTCO watchdog, re-plug restart, unclean-stop marker
**Downgraded** (value high → medium) · configure · effort S
- **What survives:** the new fact that `iTCO_wdt` (and `iTCO_vendor_support`) are blacklisted by the Ubuntu HWE package, so plan P2-5's hardware watchdog needs an explicit `/etc/modules-load.d/iTCO_wdt.conf`; verify with `wdctl` on the bench and that BIOS does not set NO_REBOOT. The unclean_stop marker is a fallback only for a hardware-watchdog reboot that P1-4's ExecStop disarm cannot cover.
- **Verifier:** re-plug and unclean death are plan P1-4; `RuntimeWatchdogSec`, module and `kernel.panic` are P2-5. `RebootWatchdogUSec` already defaults to 10 min. amr.service is installed but disabled for the trial, so adding a WantedBy changes when it starts.

#### `vda5050-v3-northbound`: VDA 5050 3.0 vehicle-side adapter
**Downgraded** (value medium → low) · new · effort M
- **Verifier:** spec facts verified at tag 3.0.0 (waitForTrigger with `triggerType LOCAL`; operatingMode enum; MOBILE_ROBOT_NOT_AVAILABLE; stopPause "can also restart … stopped with a hardware button (if configured)" must never be configured). But site decisions D5 (no central system) and D13 (AGV-01 only) mean no consumer; it adds a broker and network surface on a vehicle with no network auth. openTCS speaks only 1.1/2.0. Defer until a fleet manager or AGV-02 is scheduled.

#### `vda5050-error-levels-in-catalogue`: map the catalogue to VDA error levels
**Downgraded** (value medium → low) · augment · effort S
- **What survives:** if ever needed, a derived pure `to_vda_error()` from existing (severity, clears_by), not 85 new catalogue cells.
- **Verifier:** VDA CRITICAL means "unable to continue active order", but a start_button hold resumes the same trip, so the proposed mapping misstates it.

#### `iso3691-4-conformance-matrix`: clause matrix for software-explained behaviour
**Downgraded** (value high → medium) · augment · effort S
- **What survives:** (1) fix `RUNBOOK.md:413` to say 0.30 m/s and pin reverse speed ≤ 0.30 m/s in a test (no profile key needed); (2) a documentation matrix (clause | behaviour | code | evidence | status) for auto-resume vs "automatic restart", the 2 s horn vs warning system, pendant without enabling device under 4.9, generated or checked like the RUNBOOK §4 card. Clause numbers must be confirmed against the purchased ISO 3691-4:2023; it never becomes software.
- **Sources:** TÜV Rheinland AGV whitepaper (2020 edition clause map, Annex A Table A.1 row 1b 0.3 m/s muted detection); ISO 3691-4:2023 sample.
- **Verifier:** the claimed conflict is refuted: reverse is 0.5 × 0.60 = 0.30 m/s, not 0.4. The 0.8 m/s profile value is not the reverse base. Table A.1 0.3 m/s is from 2020, unverified for 2023.

#### `sick-driver-no-write-fork`: patch the sick driver to skip the CoLa2 data-output write
**Keep.** replace · value medium · effort M · source overlay of `sick_safetyscanners_base` + `sick_safetyscanners2` (C++, Humble)
- **What:** upstream has no passive mode: all three base constructors call `changeSensorSettings`; the ROS 2 node calls it again in `startCommunication()` and in `parametersCallback`; `use_persistent_config` only reads angles. A `write_comm_settings` flag (false here) skips all three, restoring "scanner config never written by software" while keeping the driver's decoding.
- **Sources:** SICKAG `sick_safetyscanners_base/src/SickSafetyscanners.cpp`; `sick_safetyscanners2` `SickSafetyscanners.hpp`/`.cpp`, README.
- **Target:** `amr_ws/src/third_party` overlay (~20-line patch); `nanoscan3.yaml`; `agv_core/lidarframe.py` (keep as fixture decoder or delete after).
- **Sketch:** vendor at current commits; test that no ChangeCommSettingsCommand is sent with the flag false (mock TCP client); offer upstream.
- **Risks / order:** gated on the data output being persisted in Safety Designer (`scn-sd-persistent-udp-output`; TI 8022708 §4.2.1 says a Safety Designer configuration is saved and active after restart). If persistence turns out impossible on the fitted variant, document the volatile data-output write as a reviewed exception instead. One-time C++ build; no runtime CPU change.
- **Verifier:** the write happens in `startCommunication()` and `parametersCallback`, not `setupCommunication`.

#### `blvr-1003h-error-history`: 1003h into the report zip
**Downgraded** (value low) · new · effort S
- **Verifier:** 1003h is volatile (Save=No, cleared at power-off), so it adds evidence only between a service restart and the power cycle 8130h needs. No guard change: 1003h is refused by default-deny; 40C2h/40CEh by the 4000h-4FFFh rule. Covered by `blvr-alarm-history-8130h-facts`.

#### `cf821-indonesia-band`: custom 920-923 MHz plan and matching power
**Keep.** configure · value medium · effort S · vendor tool (human)
- **What:** the reader runs on US region (902.75-927.25 MHz), which in Indonesia overlaps 900 MHz cellular spectrum. Indonesia's UHF RFID allocation is 920-923 MHz. Use REGION 0x00 custom (e.g. start 920.125 MHz, step 250 kHz, 11 channels → 922.875 MHz) or 0x08 CHINA_BAND2 restricted with CN. 0x05 MALAYSIA (919.5-922.5) starts below 920 MHz: not compliant.
- **Sources:** UHF Even Reader manual RfidFreq/RfidPower; Pepperl+Fuchs SDPPI certificate (920-923 MHz, < 400 mW EIRP, ref PERDIRJEN 161/2019); incompliancemag (Indonesia end-product approval).
- **Sketch:** a human sets it with the vendor tool (rfid.py stays read-only); replace `expect_region` with `expect_freq {region, start_mhz, step_khz, channels}` + lowered `expect_power_dbm` (schema, validation, refusal test); re-check read range at every stop.
- **Risks:** lower power shortens range; test on the floor. Regulatory call is the user's.
- **Verifier:** the current framework is SDPPI Decree 260/2024 (enforced 2024-08-11); its RFID limit was not confirmed. The 400 mW EIRP comes from one device certificate. Sources conflict; confirm with a local certification body.

### 2.12 gap: battery BMS on can0

Sheet 06 lands the BMS on TB41/TB42 (CAN H/L, no CAN GND, "BATTERY COMS CABLE"). The repo has no battery datasheet, decoder or profile key. The bus works at ~45 % load, which implies the BMS is at 125 kbps, silent, or comm-disabled. Identify first; decode second.

#### `bms-passive-cob-census`: count unrouted COB-IDs in the Router
**Keep.** augment · value high · effort S · in-process Python
- **What:** every frame no route claims is counted per (id, ext, rtr, err) with DLC, rate, first/last seen and last payload; bounded dict (~64 IDs); diagnostics row plus a one-shot log after 30 s uptime. Tells the protocol family on first deploy (11-bit 0x35x Pylontech-style, 0x180+n CANopen, 29-bit 0x18xxxxxx vendor/J1939) without stopping the service. Keeps flagging new IDs afterwards.
- **Sources:** `canopen.py:233-285` (unrouted frames dropped by SDO helpers), `verify_drivers.py:64`.
- **Target:** bounded counter class in agv_core (clock-fed), Router hook before `return m`, row in `drive_node._publish_diagnostics` (`:862`).
- **Risks:** receive-only, no TX, no guard change; one dict op per unrouted frame.
- **Verifier:** label or exclude expected unrouted traffic (SDO replies 0x581/0x582/0x58A, MLS heartbeat 0x70A until P2-3, drive heartbeats). Drop the netlink half: can0 is CANable2 slcan (`slcand -o -c -f -s4`), `ip -details` shows bitrate 0 and zero counters because slcan never reports them (`bus_health.py:6-8`). A wrong-bitrate BMS would show as drive EMCY 8120h/8140h and SDO timeouts, not error-frame growth.

#### `bms-isolated-candump-identification`: one-shot candump/canbusload capture
**Keep.** configure · value high · effort S · can-utils 2020.11.0 installed · operator step
- **What:** cheapest way to learn the BMS protocol family before decoder work: `candump -t d -x can0` with an inverse filter on known IDs for 30 s, `canbusload can0@125000 -r -t -b`, then a read-only 1000h scan (a CiA 418 BMS answers device type low word 0x01A2).
- **Sources:** linux-can/can-utils; `verify_bus.py:30-60`; `amr_ws/README.md:197-198`.
- **Risks:** do not use `verify_bus --nmt-start` or `drive_forward.py` (NMT broadcast to node 0: `verify_bus.py:178`, `drive_forward.py:184/274`).
- **Verifier:** the service does not have to be stopped: SocketCAN lets readers share can0, so a filtered receive-only candump runs alongside it. Drives are not silent after the service stops: drive_node writes 1017h = 200 ms (`drive_node.py:372`), held in RAM until a drive power cycle. `candump -e` shows nothing on slcan, so it cannot prove the bitrate.

#### `bms-decoder-batterystate`: pure BMS decoder + read-only routes publishing BatteryState
**Keep.** new · value high · effort M · `sensor_msgs/BatteryState` (core apt; amr_base already depends on sensor_msgs) · blocked on identification
- **What:** direct SoC, pack current/voltage, cell V/T extremes and fault bits instead of inferring charge from drive 40A4h bus voltage under load (sags with current, lags, plan P2-6). `present=false`, `percentage=NaN` when stale.
- **Sources:** common_interfaces humble BatteryState.msg; CiA 418 summary; Movicom BMS Mini S CANopen PDO doc; Pylontech LV CAN V1.3.
- **Target:** new `agv_core/drivers/canbus/bms.py` (per-family pure decode, clock-fed freshness 3 × period); `drive_node.py` adds Router routes and publishes `/battery_state` + `/battery_state_ui` at 1 Hz; profile `bms` block (enabled, protocol, ids with ext flag, period_s, soc_warn_pct, soc_refuse_run_pct) with schema + refusal tests.
- **Risks:** no write and no guard change if the BMS broadcasts. If its bitrate is not 125 kbps it cannot share this bus (vendor-tool job). Route by (id, ext) first (`bms-router-ext-key`). BMS values never reach gating/cmd_mux. 40A4h stays as fallback and plausibility cross-check.
- **Verifier:** conditional: if the census shows a silent BMS this collapses to `bms-poll-guard-allowlist` or nothing. Map pack temperature into `temperature`; `design_capacity` exists too.

#### `bms-soc-run-refusal`: BMS SoC/fault refuses a new run
**Downgraded** (value medium → low) · augment · effort S · already in plan P2-6
- **What survives:** P2-6's "refuse a new run below trip_low (refusal only)" takes the BMS as source when fresh, else 40A4h voltage. Hook: `run_fsm.py:93` Start gate_reason; LINE starts need the same. Never abort a run in progress; a stale BMS must not block runs.
- **Verifier:** canmon already supports `trip_low` limits (`canmon.py:143-158`). The EN 1175 replacement-edition date and the exact ISO 3691-4:2023 power-source scope wording are unverified; check against the CE technical file before citing.

#### `bms-router-ext-key`: route by (id, is_extended_id); skip RTR and error frames
**Keep.** augment · value medium · effort S · python-can 4.6.1
- **What:** python-can's socketcan backend subscribes to error frames by default (`ignore_rx_error_frames=False`), and a non-EFF error frame's `arbitration_id` is `can_id & 0x7FF` = error-class bits. CAN_ERR_BUSERROR|TX_TIMEOUT = 0x081 and BUSERROR|LOSTARB = 0x082 are exactly the EMCY routes of nodes 1/2, so `Router.recv` (`canopen.py:252`) would hand an error frame to `_make_emcy` as a drive alarm. Latent on slcan (no kernel error reports), real after an adapter swap to gs_usb/peak_usb.
- **Sources:** `canopen.py:252-267, 404-407`; python-can bus filtering docs.
- **Sketch:** skip `is_error_frame` and `is_remote_frame`, key routes on (id, ext); same in `verify_drivers.sdo_read`; FakeBus tests (extended 0x181 does not touch telemetry; error frame 0x081 is not an EMCY). Kernel `can_filters` only after the census has run.
- **Verifier:** the BMS-specific motive is weak (29-bit IDs never equal 11-bit keys; nothing sends RTR). A CANopen BMS at node 1, 2, 10 or 100 is a hard bus conflict to fix by renumbering, not in software. Must land before `can-adapter-real-error-counters`.

#### `bms-verify-bus-inventory`: BMS in verify_bus; per-node NMT everywhere
**Downgraded** (value medium → low) · configure · effort S
- **What survives:** drop the `node=0` default in `canopen.nmt()` so a future caller cannot broadcast by omission; make `verify_bus --nmt-start` and `drive_forward.py` per-node. Add the BMS to EXPECTED and teach `classify()` (masks 0x780) about 29-bit and 0x35x IDs once it is identified. Any new offline check bumps EXPECTED_CHECKS deliberately.
- **Verifier:** drive_node never broadcasts (`canopen.py:657/662/786`, `mls_track.py:315` pass a node). The bench broadcasts are Start and Enter Pre-op, never Reset; a CANopen BMS would at most start/stop its PDOs.

#### `bms-physical-layer-check`: termination, reference, bitrate at U10 acceptance
**Keep.** configure · value medium · effort S · operator task, vehicle powered off
- **What:** H-L resistance with power off (60 Ω correct, ~40 Ω = third terminator in the BMS), pack label (make/model, protocol doc, bitrate, termination jumper/DIP). No software.
- **Sources:** `proj01-sheet-06.html:50-53`, `io-mapping.md:47-50`; ISO 11898-2; Movicom and Daly protocol docs (250 kbps defaults).
- **Risks:** sheet edits only through `agent/SKILL.md` (`'?value'`, `'«placeholder»'`, interpret first). Changing BMS bitrate/termination is a vendor action.
- **Verifier:** the MLS also has no CAN GND on sheet 06; only the drives carry it (TB39/TB40).

#### `bms-poll-guard-allowlist`: request/response BMS polled through a frame-level allow-list
**Downgraded** (value low) · new · effort M · only if the census shows a request-only BMS at 125 kbps
- **Verifier:** speculative (Daly defaults to 250 kbps). guard.py is already allow-list based (ALLOWED + FORBIDDEN + `check_sensor`), but a raw 29-bit frame check is a new kind of guard function: test asserting the exact list, failure mode (a wrong data ID could switch BMS MOSFETs) and recovery path required.

### 2.13 gap: N97 power-management latency

Host facts (read-only, verifier): governor powersave, EPP balance_performance, cpuidle menu governor; cpu0 idle states POLL/C1E/C6/C8/C10 with exit latency 0/2/195/260/660 µs and target residency C6 585 / C8 1040 / C10 1980 µs; with amr.service active cpu0 entered C10 ~86 times/s; `use_rpdo` is still false, so 2 × ~1.8 ms blocking SDO per tick dominates the 20.4 ms average / 31 ms peak tick (`config.py:169-171`).

#### `pm-latency-baseline`: measure first
**Keep.** augment · value high · effort M · turbostat installed (linux-tools-6.8.0-138); rt-tests 2.2-1 in apt, not installed
- **What:** numbers that separate SDO RTT, C-state exit, frequency and thermal throttle. Fills plan P0-6(e)/A4 (grep finds no overrun stats; `drive_node.py:575-576` computes `spent` and discards it).
- **Sources:** turbostat(8); cyclictest(8) (`--latency` writes `/dev/cpu_dma_latency`, default 0); Ubuntu RT latency how-to.
- **Target:** pure stats module (period max/p99, overrun count, pump wake-lateness histogram) in agv_core or next to `gating.py`; `drive_node._loop`; existing 1 Hz diagnostics (new keys only, no msg, no colcon); RUNBOOK "CPU power baseline" procedure.
- **Sketch:** (1) during a shift: `sudo turbostat -q -s Busy%,Bzy_MHz,CPU%c1,CPU%c6,CPU%c8,CPU%c10,Pkg%pc6,Pkg%pc10,CoreTmp,PkgTmp,PkgWatt,CoreThr -i 5 -o …` (MSR reads only). (2) service stopped, witnessed: `cyclictest -m -S -p80 -i1000 -h1000 -D10m --default-system`, then `--latency=200` and `=100` to preview caps without installing anything. (3) compare before/after each change. Take the baseline before and after the RPDO switch, or PM effects are confounded with SDO RTT.
- **Risks:** cyclictest runs SCHED_FIFO; stack stopped. A step the operator saw pass is not re-run for instrumentation.
- **Verifier:** pump wake lateness includes GIL hand-off from rclpy threads, so it is an upper bound on C-state + scheduler latency; cyclictest is the platform control. `CanRouter.pump` loops `recv()` until one times out: record lateness as `perf_counter() − end` after the final None.

#### `pmqos-cpu-latency-holder`: PM QoS CPU-latency cap held by a root unit
**Downgraded** (value high → medium) · new · effort S
- **What survives:** if `pm-latency-baseline` shows a wake-lateness tail matching C8/C10 exit and turbostat shows no rise in CoreThr/PkgTmp, a tiny root holder `amr-pmqos.service` (`PartOf=amr.service`, Restart=always) holding `/dev/cpu_dma_latency` open at `${AMR_CPU_LATENCY_US}` (start 200 µs: bans C8/C10, keeps C1E/C6). Request vanishes when the unit stops; fail-to-baseline. Not `intel_idle.max_cstate`.
- **Sources:** kernel PM QoS interface and cpuidle admin guides; Red Hat article 65410.
- **Verifier:** thermally coupled on a fanless box that already throttles; worst exit cost is small next to the 3.6 ms SDO cost while `use_rpdo=false`; C8/C10 is chosen only for predicted idle above ~1-2 ms. Per-CPU `pm_qos_resume_latency_us`: writing 0 means NO constraint; "n/a" means zero latency allowed. Write `${AMR_CPU_LATENCY_US}` braced, or validate.sh's env check is bypassed.

#### `ipc-throttle-telemetry`: thermal_throttle counters next to the IPC temperature
**Keep.** augment · value medium (was high) · effort S
- **What:** `/sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_*` (count 4200, total ~13.4 s, max 29 ms in ~3 h; unprivileged) shown as "IPC 65 °C, throttled N/min" on the existing chip and optionally in drive_node's 1 Hz diagnostics, report-only.
- **Sources:** kernel intel_thermal_throttle doc; `adapter.py:108-160, 616-618, 793`.
- **Sketch:** pure reader with injectable root (second root `/sys/devices/system/cpu`), delta per 5 s window, decrease = reboot; read cpu0's package counters only. Add the `intel_powerclamp` cooling device `cur_state` (thermald runs `--adaptive`; idle injection would stall the drive thread). Test in `amr_web/test/test_operator_ux.py` (existing test at :633). Any warn threshold later = profile key + schema + refusal test.
- **Verifier:** throttle = TM1 clock modulation or TM2 frequency reduction, not a halt: a 29 ms episode slows a tick, it does not freeze it. core_throttle_count is also 4200. TCC offset unreadable without MSR, so why throttling occurs at ~65 °C (BIOS offset, PROCHOT, short hotspots) is open. `adapter.py:1057` already records a 2026-10-02 throttling incident.

#### `pstate-epp-turbo-policy`: EPP / turbo cap via a root oneshot
**Downgraded** (value medium → low) · configure · effort S
- **Verifier:** both levers are speculative and opposed (more aggressive EPP adds heat; a turbo cap costs SLAM/Nav2 headroom at load 4-6). The tick is dominated by SDO RTT until RPDO. Consider only if baseline + throttle telemetry show Bzy_MHz dips or CoreThr correlated with overruns. The "~2.9 GHz all-core turbo" is not on Intel's spec page; ExecStop must restore values captured at start. Never write `performance` to `scaling_governor` (forces EPP 0).

### 2.14 gap: package and kernel drift control

#### `ros-snapshot-apt-source`: freeze Humble on `snapshots.ros.org/humble/2026-09-14`
**Keep.** replace · value high · effort S · snapshots served for jammy amd64; Humble EOL May 2027
- **What:** the ROS binary set cannot change by accident; moving it is a one-line reviewable date edit; rollback is the same edit back plus `--allow-downgrades` (old snapshots keep exact versions; the live repo deletes them).
- **Sources:** `http://snapshots.ros.org/humble/` listing (2022-05-23 … 2026-08-07, 2026-09-14, 2026-10-12); 2026-09-14 InRelease (Origin ROS, Label humble/2026-09-14); ROS wiki SnapshotRepository (key 4B63CF8F…CBF125EA, "preview", "no bug fixes or security updates", "at least six months"); local `ros2.sources`, `apt-cache policy`.
- **Target:** new `amr_ws/deploy/ros2-snapshot.sources` (deb822, inline `Signed-By`, no deb-src) and `apt-preferences-amr` (installed to `/etc/apt/preferences.d/60-amr` by install.sh); `alpha-setup.md` §4 (repo root, ~547-580) and RUNBOOK §5.
- **Sketch:** pin `Package: *`, `Pin: origin packages.ros.org`, `Pin-Priority: -1` (hostname form: both repos publish Origin ROS). validate.sh checks no live packages.ros.org source is active. Keep `/var/cache/apt/archives` (154 ros-humble debs incl. tf2 0.25.23); do not `apt clean`.
- **Risks:** wiki discourages snapshots on production robots "directly" (this vehicle effectively bundles a fixed artefact); no security fixes, which is already the case today with no record. `https://` fails TLS (CloudFront mismatch); integrity rests on the signed InRelease, as with packages.ros.org over http.
- **Verifier:** all 266 installed ros-humble packages match 2026-09-14 exactly (tf2 0.25.23 …20260907, foxglove 3.5.0 …20260908, nav2 1.1.20 …20260908); 2026-10-12 changes 58 (tf2 family 0.25.24, foxglove 3.6.0, nav2/robot_localization/slam_toolbox rebuilds; rclpy 3.3.22 unchanged). `/etc/apt/sources.list.d/ros2.sources` is owned by package `ros2-apt-source` 1.3.0 as a plain file (not a conffile), so any reinstall/upgrade rewrites it to live: put the snapshot in its own file and `apt purge ros2-apt-source` (or hold it and delete its file). Pin `Package: *` because python3-colcon-*, rosdep and vcstool also come from packages.ros.org. The vehicle owner ran `apt install` on 10-17 and 10-18: the partial-sync risk is real.

#### `kernel-meta-hold`: hold HWE metas, drop GA 5.15 metas, check uname in validate
**Keep.** configure · value high · effort S
- **What:** no new kernel ABI (each brings its own slcan/gs_usb/peak_usb/igc/i915 modules) unless done on purpose. Today two meta chains are installed; linux-generic 5.15.0.187 has 5.15.0.198 pending; `GRUB_DEFAULT=0` boots the newest.
- **Sources:** Ubuntu kteam HWE kernel reference (22.04.5 HWE = 6.8, EOL Apr 2027); unattended-upgrades 50unattended-upgrades.Ubuntu; local apt-cache, `/etc/default/grub`, `/boot`; `alpha-setup.md:212-214` (HWE chosen for N97 iGPU and i226 NIC).
- **Sketch:** `apt-mark hold linux-generic-hwe-22.04 linux-image-generic-hwe-22.04 linux-headers-generic-hwe-22.04 linux-firmware`; `apt purge linux-generic linux-image-generic linux-headers-generic`; moving later = unhold, install the specific image, staged procedure, re-hold. validate.sh checks `uname -r` (via the platform manifest).
- **Risks:** kernel security fixes stop until a deliberate move; record it; re-evaluate at jammy standard EOL (Apr 2027).
- **Verifier:** after the purge, `apt-mark manual linux-image-5.15.0-187-generic linux-modules-5.15.0-187-generic` (and -extra) or a later autoremove deletes the GRUB fallback. Also hold or record `intel-microcode`.

#### `unattended-upgrades-amr-policy`: explicit policy, timers masked, maintenance window
**Downgraded** (value high → medium) · configure · effort S
- **What survives:** `52amr-unattended` drop-in (blacklist `linux-`, `ros-humble-`, `nodejs`; `Automatic-Reboot false`; `InstallOnShutdown false`; `Remove-Unused-Kernel-Packages false`; `APT::Periodic::Unattended-Upgrade "0"`), installed by install.sh; `systemctl mask apt-daily.timer apt-daily-upgrade.timer` as a RUNBOOK §5 step (not install.sh: validate.sh forbids it changing unit state); monthly witnessed `sudo unattended-upgrade -v` in a RUNBOOK §7 maintenance window; validate.sh warns on enabled timers and prints the pending count.
- **Verifier:** both timers disabled and inactive since ~2026-08-28; Allowed-Origins are Ubuntu/ESM only; ROS was never eligible. With the kernel hold and ROS snapshot, the blacklist is a second layer. Other agents present: packagekit (static, D-Bus activated), `update-notifier-download.timer` (ran 13:11 today; worth masking), `fwupd-refresh.timer` (metadata only).

#### `needrestart-amr-override`: never auto-restart amr.service from an interactive apt run
**Keep.** configure · value medium · effort S · needrestart 3.5-5ubuntu2.4
- **What:** in an interactive `apt upgrade`/`apt install` over SSH, needrestart preselects services mapping replaced libraries (amr.service after any ROS/libssl/libc update; its Python scanner also flags changed .py files) and Enter restarts them. A restart cannot start motion, but it is an unwitnessed stack restart mid-shift.
- **Sources:** local `/etc/needrestart/needrestart.conf` (lines 35-38, 64-74, 183-186), `/usr/sbin/needrestart:224-227`, `/etc/apt/apt.conf.d/99needrestart`; Ubuntu discourse (24.04 auto-restart change).
- **Sketch:** `amr_ws/deploy/needrestart-amr.conf` → `/etc/needrestart/conf.d/amr.conf`: `override_rc` for `^amr\.service$`, `systemd-networkd`, `chrony`, `nginx` (kiosk holding page) = 0; `kernelhints = -1`. `perl -c` check; validate.sh checks presence.
- **Verifier:** default conf already deselects `^NetworkManager`; that entry is redundant.

#### `platform-manifest-lock`: pure manifest module + committed accepted baseline
**Keep.** new · value high · effort M · stdlib + dpkg-query/uname/modinfo
- **What:** any behaviour change can be tied to a version change. The report zip carries what changed since the accepted baseline; validate.sh fails loudly before cutover if the box is not the accepted platform. RUNBOOK §7 points to "tags and manuals/vehicle-reports/", neither of which exists (only tag: legacy-final).
- **Sources:** dpkg-query(1), modinfo(8); `reports.py` build() (no versions/kernel/git HEAD); `validate.sh`.
- **Target:** new `agv_core/platform_manifest.py` (parse/diff/classify, subprocess injected, no ROS/Flask); `amr_ws/deploy/platform.lock`; `validate.sh`; `reports.py` (`platform.txt`, `platform-diff.txt`, timeout + "(manifest unavailable: …)" like `_journal()`); `tests/test_platform_manifest.py`; EXPECTED_CHECKS bump; RUNBOOK §5/§7.
- **Sketch:** collect `uname -r`, `/proc/cmdline`, ROS apt source line (snapshot date or live), `apt-mark showhold`, dpkg versions (ros-humble-*, linux-image/modules, linux-firmware, libc6, libssl3, libstdc++6, python3.10, can-utils, intel-microcode), `modinfo -F srcversion` for slcan/gs_usb/peak_usb/can_dev/igc, pip `--user` freeze filtered to the alpha-setup §5.2 set, `snap list`, git HEAD + dirty count. Kernel/ROS/python-can mismatch = FAIL, others WARN; explicit printed `--allow-drift`. `python3 -m agv_core.platform_manifest accept` writes the lock at vehicle acceptance; its sha256 goes in the acceptance record. Runs only at report/validate time.
- **Verifier:** validate.sh also runs where no accepted platform exists: FAIL only when `platform.lock` exists and the host matches it, else WARN.

#### `lvm-snapshot-staged-move`: staged platform move with an LVM root snapshot
**Downgraded** (value high → medium) · augment · effort M
- **What survives:** a RUNBOOK §5 "Moving the platform" / §7 "Platform rollback" procedure for a rare event: copy `~/.amr` off the box; `lvcreate -s -L 20G` on `ubuntu-vg/ubuntu-lv` and tar `/boot` and `/boot/efi`; switch the snapshot date; `apt-get install --only-upgrade` the ros-humble set; clean `colcon build`; `python3 tests/run_all.py`, focused pytest, one unified sim (sequential, own domain); re-check foxglove assumptions against 3.6.0; operator-witnessed vehicle steps; accept (manifest accept, `lvremove`) or reject (`lvconvert --merge` + reboot, restore `~/.amr` items). Never move kernel and ROS in one step. Move the whole sync, never tf2 alone (2026-10-12 nav2 etc. are rebuilds after tf2 0.25.24).
- **Verifier:** once the snapshot source exists, the date revert + `--allow-downgrades` from `platform.lock` is already an exact ROS rollback. The W8 data volume is designed but not deployed, so `~/.amr` is on the root LV and a merge reverts it: step 1 is mandatory. VG free space is inferred from lsblk only (~129 G); check with `sudo vgs`.

#### `snapd-refresh-hold`: hold all snap refreshes; remove unused lxd and cups
**Keep.** configure · value medium · effort S · snapd 2.77.1
- **What:** snapd refreshes every 4 h during shifts (last 13:12 WIB today) and changes mesa-2404/gnome-46-2404, the GPU/GTK runtime under the held chromium kiosk (`alpha-setup.md:810-811` holds only chromium).
- **Sources:** snapcraft forum t/7022; Ubuntu blog on refresh holds; local `snap refresh --time`, `snap list`.
- **Sketch:** `sudo snap refresh --hold` (all, forever); `sudo snap remove lxd cups` after confirming unused (`snap services`); refresh in the monthly window, then re-hold; add `snap list` and `snap refresh --time` to the manifest.

### 2.15 gap: I/O truth vs electrical sheets

#### `io-mapping-parsed-profile-test`: parse io-mapping.md and assert the profile DI/DO map
**Keep.** new · value medium (was high) · effort S · stdlib, offline suite
- **What:** one drift check between the wiring source of truth and the profile. Today `test_panel.py:165-188` hand-copies a subset. Drift it would surface now: (a) all `do_names` are `[SPARE]` while sheet 09 has DO0/DO1 = horn sounds 1/2; (b) `dio.motion_on = [0, 8]`, but DO8-DOB are "NOT USED" (sheet 09:198); (c) `num_do 16` vs "16DI+12RELAY"; (d) resolved 2026-10-28: io-mapping now names DI08 the Manual Arm switch, matching the profile.
- **Sources:** `io-mapping.md` §2-3; `tests/test_config.py:442` (parse-don't-restate precedent); `config.py:703-737, 1092-1130`; `tests/run_all.py:87`.
- **Target:** new `tests/test_wiring.py` registered in `run_all.py` MODULES with a deliberate EXPECTED_CHECKS bump.
- **Sketch:** ~40 lines: split on headings, read pipe tables keyed by first column, expand ranges, classify wired/spare/not_used by keyword. Assert panel/pendant channels map to rows naming START/RESET/selector/FORWARD…; `di_manual_arm` → the row naming "Safety PLC Q3" and in the COM1 range DI08-DI0F; every channel in motion_on/alarm_on/movement_horn/horn.do_channel is a wired DO; no non-`[SPARE]` name on a not_used row; `num_di/num_do` ≤ header counts. `KNOWN_OPEN` = exact-set equality for {DO8 in motion_on, num_do 16 > 12} (plan P2-8 Q5 "ask, don't change") and `do_names[0..1]` until `profile-do-names-from-sheet` lands. Reworded table → clear "table not found" failure.
- **Verifier:** it catches profile-vs-doc drift, not doc-vs-real-wiring drift (the 2026-09-16 DI misread was the latter). Selector polarity is not drift: the operator settled it (`test_panel.py:163`); add a one-line io-mapping note. Keep the operator-verification comments in `test_panel.py`. Reading `documentation/electrical/` is a "work there" event: SKILL.md applies; no sheet is changed.

#### `fx3-tag-name-csv-export`: Flexi Soft Designer tag-name export
**Downgraded** (value high → medium) · new · effort M · Windows engineering tool
- **What survives:** open the FX3 project offline once (report/logic view only; never Transfer, never Import: tag import discards unsaved changes irreversibly), read what Q3 and Q4 actually encode and the configuration CRC, and write the answer into `io-mapping.md` §2. That answers plan Q5 (what does Q3 → DI08 encode; arm_policy powers the drives in MANUAL on it). Committing a CSV is optional afterwards.
- **Verifier:** feature confirmed (release notes im0038815; Safety Designer im0081083), but no FX3 project file exists in the repo or on the IPC and nothing records who holds it (possibly the panel integrator). Tag names are labels; the meaning is in the logic.

#### `fx3-q4-com1-group-constraint`: any FX3 status output lands on DI09-DI0F
**Downgraded** (value medium → low) · augment · effort S
- **What survives:** one check inside `io-mapping-parsed-profile-test` (`di_manual_arm` in DI08-DI0F) and a note next to the Q4 row in io-mapping.md: "COM1 group, test pulses off". Schema/cross-check only when the Q4 key lands.
- **Verifier:** reasoning correct (FX3-XTIO Q outputs switch high-side 24 V; COM0 = 1P24 with contacts to 1N24, so DI07 would never read). Test pulses are sub-ms; `debounce_scans=2` would mostly absorb them, but test pulses off stays right.

#### `sheet-consts-vs-io-mapping`: sheet 08/09 data consts vs io-mapping.md
**Downgraded** (value medium → low) · augment · effort S
- **What survives:** a few checks in the same `test_wiring.py`: Q3 end labels agree across sheets 08/09; HORN = DO0/DO1; wired DI set from START/REMOTE/PENDANT/Q3 consts. Stdlib regex over named consts only, clear "const not found" failure; no node dependency.
- **Verifier:** every sheet edit already passes the SKILL interpret-confirm-build loop. "NOT USED" facts for DI07, DI09-DI0F and DO8-DOB are `s.text()` strings (`proj01-sheet-09.html:173, :198`), not consts; the DI const lists DI07 although unused.

#### `profile-do-names-from-sheet`: name DO0/DO1, mark unwired DOs, leave DO8/num_do alone
**Keep.** configure · value medium · effort S · `profiles/agv-01.json dio.do_names` only
- **What:** the operator's I/O page (`io.html:29`) stops calling the two horn coils `[SPARE]`. This is the half of plan P2-8 the plan already authorises.
- **Sketch:** short labels for the 1280×720 page at UI scale `l`: `Horn snd1 (move)`, `Horn snd2 (alarm)`, DO2-DO7 `[SPARE]`, DO8-DO11 `n/c`, DO12-DO15 `no relay`; keep 16 entries. No schema change (`_read_io_names` only enforces count = num_do; nothing parses the names).
- **Risks:** display-only. Do not remove DO8 from `motion_on` or set `num_do` to 12 (Q5). A Modbus coil read cannot show relays 12-15 are missing (16 coils read fine today, `dio.py:261`); only the hardware settles it.
- **Verifier:** `config.py:719-727` already records DO00 = movement horn, DO01 = alarm horn (operator 2026-10-02), consistent with sheet 09. `demo_server.py` DO_NAMES fixture is separate.

---

## 3. Device features not yet used

Only features a kept or downgraded candidate relies on. "Use" says what to do with it; "no" means documented here so nobody re-researches it.

| Device | Object / feature | Manual ref | Use |
|---|---|---|---|
| BLV-R | TPDO3/TPDO4 (1802h/1803h, 1A02h/1A03h), type FEh/FFh, inhibit + event timer | `blvr_canopen.md` p.31-32, p.77-87 | Push 60FDh/407Bh and the analog health block (split in §0); re-apply in prepare() every time (volatile without 1010h) |
| BLV-R | 407Bh Information status (compatible) | function manual p.334, p.345-347 | Early-warning and config-drift edges; bench-confirm layout and word order first |
| BLV-R | 603Fh latest NV alarm (+FF00h) | `blvr_canopen.md` line 4386; function manual p.459 | Preflight/diagnostics: last stop cause survives the power cycle |
| BLV-R | 1003h pre-defined error field | `blvr_canopen.md` p.61 | Preflight log only (volatile) |
| BLV-R | 4041h-404Ah (alarm history 1-10 by NET-ID pattern) | function manual NET-ID 0041h-004Ah | Undocumented in the OD: read-only bench probe; abort = absent |
| BLV-R | 40A2h number of boots, 40A9h continuous uptime | `blvr_canopen.md` p.93 | DRIVE_REBOOTED reason; boot record in preflight |
| BLV-R | NMT boot-up 0x700+n data 0x00 | `blvr_canopen.md` p.21 §4.3 | Already decoded, unused: feed `decide()` a rebooted flag |
| BLV-R | 60FDh digital inputs (bit 3 HWTO; R-OUT0-15 default functions) | `blvr_canopen.md` p.113 | Per-wheel STO evidence; read by SDO first (R-OUT assignments may differ) |
| BLV-R | 6085h / 605Ch / 605Bh readback | `blvr_canopen.md` p.99-100 | Refuse to arm if the two drives disagree |
| BLV-R | SYNC producer (1005h bit 30, 1006h) | `blvr_canopen.md` p.21 §4.4, p.62-63 | No: bus load; use kernel RX timestamps |
| BLV-R | Touch probe 60B8h-60BDh, 60D5h | `blvr_canopen.md` p.108-110 | No: first-event default needs a denied re-arm write |
| BLV-R | Driver simulation mode (virtual motor), reg 1022/1023 | function manual ch.9 §10 p.500-501 | Optional MEXE02 bench HIL; revert checklist with LED check |
| BLV-R | ALM-RST assignable input | function manual p.451 | Not wired; whether to add a panel button is open plan Q4 |
| SICK MLS | TPDO7 gyro x,y,z + ms stamp (1806h:01, :05) | MLS OI Table 4 p.29-30, Table 16 p.40, §8.1.3 p.40 | Stream yaw rate at 20 ms; :05 must be non-zero |
| SICK MLS | TPDO2 line width + line level | MLS OI Table 11 p.39 | Only if tape_health needs finer than `track_level` |
| SICK MLS | 1800h:05 TPDO1 event timer (0xFE/0xFF only) | MLS OI §8.1.3 p.40, Table 4 p.29 | Read at start; derive gap thresholds (plan P1-8) |
| SICK MLS | TPDO1 variant 4 "Standard enhanced compensated" | MLS OI Table 10 p.39, §8.4.6 p.51 | Only if bench B7 fails; confirm 202Dh:02 meaning |
| SICK MLS | IMU 640 ms initialisation (all outputs zero) | MLS OI §8.6 p.54 | Blank samples after a sensor reset |
| SICK MLS | Raw gyro frame independent of 2027h | MLS OI §8.6.7 p.56 | gyro_sign is a one-time vehicle check |
| SICK MLS | 2070h:02/03 lifetime max/min temperature | MLS OI Table 4 p.35 | One line in the read_mls snapshot |
| SICK MLS | Marker direction by a1 vs a2 after inversion | MLS OI §8.5 p.52 | Sharpen bench B6; no code before |
| nanoScan3 | Data output saved in Safety Designer (continuous to host) | TI 8022708 §4.2.1 p.10-11, index 177 p.57 | Survives scanner power cycles; prerequisite for a no-write driver |
| nanoScan3 | Status overview (config_state, error_info_code) | TI 8022708 §6.3.1.3.1 p.47-49 | Refuse AUTO Start when config ≠ Verified; error class → recovery text |
| nanoScan3 | Device status block (contamination, reset required, monitoring case) | TI 8022708 §6.1 Table 4 p.21 | Via driver `/diagnostics` State; not via raw_data in Python |
| nanoScan3 | Application outputs `is_valid` per cut-off path, active case | TI 8022708 §6.1 Table 9 p.26 | Invalid = UNKNOWN in the mux; case report-only |
| nanoScan3 | Object detection block (deactivatable) | TI 8022708 Table 7 p.24, p.62 | Turn off: ~3.5 KB/telegram |
| nanoScan3 | Configuration metadata / overall checksum | TI 8022708 §6.3.1.2.5 p.44-46 (byte order reversed vs SD) | Pin in profile; refuse AUTO on mismatch |
| nanoScan3 + FX3 | Monitoring-case switching by speed/segment | TI 8022708 Table 8 p.25, Table 10 p.28 | Later safety project, humans only |
| Flexi Soft FX3 | XTIO Q4 (spare) | `io-mapping.md` §2 | Non-safety "E-stop/STO active" → DI09 |
| Flexi Soft FX3 | FX0-GMOD Modbus TCP gateway | SICK im0078284 | Only if per-function state is needed; check CPU compatibility |
| Flexi Soft FX3 | FX3-MOC drive monitor (SLS, SDI, speed-switched fields) | SICK FX3-MOC100010 datasheet | Later item already in speed plan 1 §7 |
| Flexi Soft Designer | Tag-name export, report/logic view | SICK im0038815, im0081083 | Read Q3/Q4 meaning once, export-only |
| CF821 reader | 0x0072 GET_DEVICE_ALLPARAM | vendor manual 0x0072 table; `CFApi.h:424` | Heartbeat + continuous param check |
| CF821 reader | REGION 0x00 custom plan / 0x08 with CN; RfidPower | vendor manual RfidFreq/RfidPower | 920-923 MHz plan, lower power (vendor tool) |
| CF821 reader | Q value, Session, FilterTime, BufferEN | vendor manual 0x0071/0x0072 | Bench row; assert in profile; FilterTime and BufferEN stay 0 |
| CF821 reader | 0x0073 read-permission mask | `CFApi.h` PermissonPara; vendor manual | Optional human-set second layer |
| CK-TP5163 DIO | Holding regs 0x20 (DO word), 0x22 (DI word) | datasheet Vr1.1 p.7-8 | Documentation only; keep FC05 per-coil writes |
| CK-TP5163 DIO | Dual-port on-chip cascade | datasheet p.7 | Bench: does an unpowered module cut the RFID reader? |
| N97 IPC | iTCO hardware watchdog (blacklisted by HWE package) | `/lib/modprobe.d/blacklist_linux-hwe-6.8_*.conf` | Plan P2-5 needs a modules-load.d override |
| N97 IPC | PM QoS `/dev/cpu_dma_latency` | kernel PM QoS doc | Only after baseline data |
| N97 IPC | `thermal_throttle` counters, `intel_powerclamp` state | kernel intel_thermal_throttle doc | HMI/diagnostics telemetry |
| CAN adapter | Kernel-native peak_usb (berr-counter, restart-ms, HW timestamps) | local `peak_usb.ko`; kernel CAN doc | Replace slcan CANable2 |

---

## 4. Keep hand-built

Engines where the survey looked for a replacement and confirmed the hand-rolled code is the right call.

| Engine | Why it stays |
|---|---|
| `lidarframe.py` / no-write scanner policy | No upstream passive mode exists: all three `sick_safetyscanners_base` constructors and the ROS 2 node's `startCommunication()`/`parametersCallback` write the CoLa2 data-output config. The repo's reason for hand-rolling stands. Path forward is the patched driver (`sick-driver-no-write-fork`) after Safety Designer persistence; keep `lidarframe.py` as the fixture decoder until then. |
| DriveLink, `decide()`, Router (drive_node) | python-canopen 2.4.1 is present, but its `BaseNode402.reset_from_fault` writes controlword bit 7 (denied), and the tested decide()/R04 semantics and single-thread scheduling would be lost. Library at most in bench tools, and even there the gain is small. |
| guard.py | No library offers a write allow-list; python-canopen's single TX choke point would need a second guard to keep in sync. Every surveyed CAN change passes guard by rule or needs an explicit tested entry. |
| `gating.py` + mux | No twist_mux-style package takes authority from lease, panel and permit instead of the command streams, or zeroes at once on expiry. Strengthen with Hypothesis stateful tests, monotonic clocks and `is_valid`; do not replace. |
| Scanner field interpretation (`scanner_fields.*`) | Fields are scanner-evaluated outputs; point-cloud collision monitors do not apply; software never writes scanner config. |
| Route executor + Nav2 minimal set | No BT/planner by design ("nothing undrawn can move"). Survey adds plugins at the edges (goal checker, fault reporting, VP A/B), not a navigator. opennav_docking rejected for the same reason. |
| Readiness FSM + scan consistency | Humble nav2_amcl exposes no absolute likelihood or confidence; `/particle_cloud` weights are normalised and uniform after resample. Operator confirmation plus an independent scan check remains the only sound READY. |
| `relocalize.py` | slam_toolbox humble welds a START_AT_GIVEN_POSE scan regardless of match response; relocalize is the only guard. BnB deferred, distance field later. |
| Gyro bias estimator | robot_localization has no bias state; imu_complementary_filter detects stillness from the gyro itself (rejected on purpose); fusioncore needs absolute heading. Add only the P1-7 bound. |
| Tape engine port (`autopilot.py`, `branch.py`) | Verbatim port by design. Curvature FF and rear-sensor heading both rejected for now; cheaper levers (k_ratio steps) first. |
| Tape teach `mean_leg` | DTW rejected: points are already projected perpendicularly onto each pass and resampled spatially every 5 cm. |
| RFID driver (`rfid.py`) | Vendor SDK is a Windows DLL; driver stays read-only. Survey changes the heartbeat opcode and adds checks, not the driver. |
| DioLink | pymodbus sync client on its own thread is right for one 50 ms poller; the async client adds an event loop for no gain. Tune `retries` with P1-10. |
| `sdnotify.py` | Equivalent to python3-systemd `daemon.notify`, which is deliberately not a dependency. Add `STATUS=`, keep the ten lines. |
| `uptime.py` marker | journald cannot tell a power cut from a hard reset; the marker stays primary. Add `boot_id` and `$SERVICE_RESULT`. |
| Process groups (`process_supervisor.py`) | cgroup delegation rejected (no `process_group=` on Python 3.10, `preexec_fn` unsafe with threads, allow-list breakage). Use `systemd-run --user --scope` only in tests. |
| Map bundles / stores | fs-verity rejected (SHA-NI hashes 94 MB in 0.061 s); `load_map` rejected (breaks one-revision-per-launch). |
| Map merge (planned) | Existing tools lack refinement, gates and provenance; plan §8.1 stands. |
| `grid.py`, `png.py` | cv2 kept out on purpose (user-site numpy/opencv pairing; plan 4.5 allows only lazy cv2). Tune `png.py` with `Z_RLE`, do not swap encoders. |
| Typed device health (`DeviceHealth.msg`, plan P1-1) | diagnostic_aggregator/common_diagnostics rejected as primary transport: string key/values against "codes are message fields", no correlation, extra Python processes. diagnostic_updater only for engineer/bag views. |
| Owner locks, domain guards | Nothing in the OS prevents two can0 openers or a fake base on the live domain; the vcan emulator review showed the guards must even be tightened (`open_bus` fallback). |
| Event ring + event log | Low-rate, dependency-free; only `tail()` across rotated files needs fixing. |
| Demo server | Runs the real app with no ROS on a laptop; MCAP replay inside it rejected in favour of `ros2 bag play` into the real web_node. |
| Commissioning engine | robot_calibration's base node publishes its own velocity commands (bypasses panel-owned entry); borrow the method into `agv_core/odocal.py`, keep the engine. |

---

## 5. Rejected

| Candidate | Area | Reason |
|---|---|---|
| `allantools-gyro-noise` | mls | Not worth it: sigma already measured by `read_imu` (2026-09-03); below 1 LSB the Allan numbers are quantisation-dominated; pulls numpy/scipy/matplotlib as runtime deps. |
| `mls-offset-calibration-202b` | mls | Already in repo as a decision: guard refuses 202Bh (tested); A13 sanctions keypad calibration with teach unlocked. A software path is a footgun (calibrating over tape blinds detection). |
| `mls-polarity-zone-tape` | mls | Already weighed (marker plan A2): polarity lock adopted; site design needs no further cue. |
| `python-canopen-bench-identity` | mls | Already covered: 1018h identity and 2019h are read; a 40-line segmented read would beat a dependency that bypasses guard. |
| `pgv100-position-tags` | line-engine | Not worth it: ±0.2 mm vs a ±10 cm station requirement; camera, floor tags, RS-485 driver, L effort. |
| `blvr-touch-probe` | line-engine | Not worth it: needs a non-existent station sensor plus 4xxxh/60B8h writes widening guard; gains a few mm. |
| `diag-updater-track-rate` | line-engine | Duplicates drive_node diagnostics and plan P1-1; FrequencyStatus gives no p99 jitter. |
| `teach-dtw-median` | line-engine | Misreads `mean_leg` (already perpendicular projection + 5 cm spatial resampling); spread flag already catches a bad pass. |
| `opencv-distance-transform` | mission-nav | No CPU problem; `PYTHONNOUSERSITE` fix would break the deliberate numpy 2.2.6 / opencv 5.0 pairing; map-merge plan chose no cv2. |
| `opennav-docking-station-stop` | mission-nav | Invariant conflict: undrawn autonomous approach; needs a new MotionPermit mode in `gating.py`/mux; Humble 0.0.2 is a stale snapshot. |
| `fsverity-revisions` | localization-maps | Not worth it: 94 MB verifies in 0.061 s; needs a root-fs feature change. |
| `mapserver-load-map` | localization-maps | Conflicts with one-exact-revision-per-launch; leaves executor, monitor, web and loc map out of step. |
| `gyro-residual-from-map-heading` | localization-maps | Already in repo (re-estimate on every still window); signal confounded with wheel scale and slip. |
| `cgroup-delegation-per-role` | supervisor-ops | Python 3.10 lacks `process_group=`/CLONE_INTO_CGROUP; `preexec_fn` unsafe in a threaded supervisor; reworks the bounded stop path; CPU-share part is plan P2-5. |
| `qos-deadline-base-liveness` | supervisor-ops | Real fix is calling `rd.base_missing()` after boot; deadline QoS needs publisher changes in the safety-listed mux and adds silent-mismatch failure modes. |
| `fx3-sls-cap-contract` | gating-motion | False premise: no FX3 SLS exists (README:279, CPU + XTIO only). |
| `mcap-replay-demo` | hmi-tooling | `ros2 bag play` into the real web_node does the same with no code. |
| `rfid-temperature-read` | peripherals | 0x0061 undocumented (memory rule: no undocumented opcodes); misses attributed to RF margin; watch on the bench with the vendor tool. |
| `rs485-isolated-usb-adapter` | peripherals | No RS-485 device planned; existing desk research already names the adapter route. |
| `fault-relay-raw-topics` | sim | Plan P3-2 chose semantic per-fake hooks; a byte relay replays old stamps (wrong failure model) and reroutes every faked topic. |
| `vdma-lif-tape-graph-export` | ecosystem | No consumer (D5), graph not yet run on the floor; revisit with a fleet decision. |
| `opentcs-vda5050-agv02` | ecosystem | Out of scope (D5/D13); openTCS adapter speaks VDA 5050 1.1/2.0 only, so 3.0 zones are unavailable. |
| `diagnostic-aggregator-common` | ecosystem | Duplicates `disk.py` and `read_ipc_temp`; conflicts with typed DeviceHealth (codes as fields). |
| `irq-thread-colocation` | gap: N97 PM | xhci IRQ already on CPU1 alone; pinning a non-RT thread on a loaded CPU likely adds run-queue delay; per-CPU QoS step as written does the opposite (0 = no constraint). |
| `wireviz-safety-harness` | gap: I/O truth | A second hand-maintained wiring truth; GraphViz output breaks the JIS style rule; sheet consts already hold tb/end/w fields for a stdlib extractor. |

Also effectively parked although kept as downgraded: SYNC-sampled TPDOs, BCM dead-man heartbeat, touch-probe latch, curvature preview, rear MLS, preempt=full/SCHED_FIFO, graceful controller, BnB matcher, laser_filters, tf2_web_republisher, SSE, i18n, VDA 5050 adapter, BMS poll allow-list, EPP/turbo policy, cyclone multicast, events TRANSIENT_LOCAL, FX0-GMOD gateway, monitoring-case switching, external watchdog relay.

---

## 6. Suggested order

Verification follows the repo policy: ordinary edits get focused unit/contract tests only; the unified sim runs once per milestone, sequentially, on its own `ROS_DOMAIN_ID`; tolerances are settled on the vehicle; a step the operator saw pass is PASS and is not re-run for instrumentation. Nothing below starts/stops amr.service, sends CAN frames or runs bench tools until the user asks.

### P0: configuration wins and closing holes (S, no new dependencies)
| Item | Verification |
|---|---|
| Foxglove read-only lockdown (`initialpose` only) | Launch-args unit test asserting whitelists/capabilities; `cd amr_ws && ruff check src/`; engineer confirms 3D view + pose estimate on the vehicle |
| Guard bypass fixes: `drive_forward.sdo_write` and `read_imu.enable_tpdo` through guard | New tests in `tests/` asserting refusal of denied objects via those paths; `python3 tests/run_all.py` with deliberate EXPECTED_CHECKS bump |
| Freeze platform: ROS snapshot 2026-09-14 source + `Package: *` pin, purge/hold `ros2-apt-source`, kernel meta hold (+ `apt-mark manual` 5.15.0-187), snap hold, needrestart drop-in, unattended policy drop-in, timers masked | `bash -n`/`validate.sh` checks for the new deploy files; `apt-cache policy ros-humble-tf2` shows the snapshot as candidate; `apt-mark showhold`; `perl -c` on the needrestart conf |
| RUNBOOK reverse wording 0.30 m/s; test pinning reverse ≤ 0.30 m/s | Focused pytest on the route compiler test |
| `amcl.yaml` save_pose_rate comment; `nanoscan3.yaml` intrusion comment; io-mapping CK-TP5163 name | Doc-only; no test |
| `profile-do-names-from-sheet` + `io-mapping-parsed-profile-test` (KNOWN_OPEN for Q5 items) | `python3 tests/run_all.py` with EXPECTED_CHECKS bump; I/O page fits at scale `l` (existing layout test) |
| `zlib-rle-png` + bounded PNG/grid caches | Existing png round-trip tests; focused `amr_web/test` |
| `scn-drop-intrusion-block` (driver param, plus yaml comment) | Before/after driver %CPU and `/output_paths` inter-arrival with bag_report on the next vehicle run |
| `bms-router-ext-key` (skip error/RTR frames, key on (id, ext)) | FakeBus tests in `test_canopen.py` |
| `lifecycle-event-bringup` (`attempt_respawn_reconnection: false`) | `test_launch_layers.py` new assertion |
| systemd: `After=`/`WantedBy=canable@can0.service`; reset-failed sudoers; tmpfiles + `--disable-external-lib-logs` | `validate.sh` (unit env, sudoers grep); takes effect only at the witnessed enable cutover; operator re-plug check during U10 |

### P1: evidence and explanation (S/M, mostly in-repo)
| Item | Verification |
|---|---|
| tf2 0.25.24 via whole 2026-10-12 snapshot move (staged procedure, `~/.amr` copied off) | Clean `colcon build`; `python3 tests/run_all.py`; focused pytest; one unified sim; operator-witnessed vehicle run with `/scan_gated` unchanged, then one consumer on raw `/scan` for a long run |
| `platform-manifest-lock` (accept at the same time) | `tests/test_platform_manifest.py` (injected subprocess); EXPECTED_CHECKS bump; report zip contains `platform.txt` |
| `rosbag2-snapshot-mcap` black box (low-rate topics, `--node-name amr_blackbox`) | Bench: one snapshot → footer written, reindex/open in bag_report; pidstat CPU on the N97 before default-on; pure trigger-policy test |
| `scn-sd-persistent-udp-output` (human, Safety Designer) then `scn-diag-status-overview` | Operator power-cycles the scanner once and sees data return; pure `scanner_health` test with a recorded DiagnosticArray |
| `scn-outputpaths-valid-safe` | New gating tests (invalid → no resume; unknown case → restrictive); failure mode/recovery stated in the change summary |
| `steady-clock-freshness` (plan P0-7 scope) | Future-stamp test; mux `_now` monotonic contract test; chrony drop-in check in validate.sh |
| `rfid-0072-heartbeat` | Unit tests for Heartbeat arming on 0x0072 and edge-triggered mismatch logging; bench reads/s with and without 1 Hz 0x0072 (operator) |
| `nav2-lifecycle-health-after-commit` | Pure `layer_health` test; opt-in sim test killing a Nav2 node shows LAYER_INACTIVE inhibit |
| `waitress-wsgi` + cut `adapter._call` timeouts | Focused `amr_web/test`; operator holds jog over Wi-Fi on the vehicle |
| `uptime-boot-id-and-service-result`, `sdnotify` STATUS= | Pure classify() tests with injected boot ids; `validate.sh` for ExecStopPost |
| `fx3-spare-q4-status-bit` (FX3 change by a human; sheets via SKILL workflow) | Profile schema + refusal test; panel_io test; operator presses E-stop and sees the explanation |
| `blvr-tpdo3-hwto-speeddev` + `blvr-tpdo3-tpdo4-monitor` + `blvr-407B-information-bits` (one TPDO3/TPDO4 change) | Tests: mapping steps pass guard; decoders for packed frames; `decode_info` edges. Bench (operator): 60FDh by SDO, MEXE02 information monitor comparison, then E-stop with TPDO3 observed (answers P1-14) |
| `blvr-alarm-history-8130h-facts`, `blvr-bootup-reboot-detect` remnant | `decide()` table rows for rebooted; preflight read tests with FakeBus |
| `bms-passive-cob-census`, then `bms-physical-layer-check` at U10 | Pure counter test; first deployed run reads the census row; operator measures H-L resistance powered off |
| `pm-latency-baseline` + `ipc-throttle-telemetry` | Fake-clock stats test; sysfs fake-tree test in `test_operator_ux.py`; one shift of turbostat data, before and after the RPDO switch |
| `sensor-driven-tick` (log no-new-seq fraction first) | Node fake-clock test (49.7 Hz samples → no zero-delta derivative ticks) |
| `hypothesis-stateful-gating` | Runs in `amr_base/test` with derandomize; not counted in EXPECTED_CHECKS unless deliberate |
| `fake-output-paths-from-field-geometry` + P3-2 scripted overrides | `test_launch_layers` assertion (never on vehicle, refuses domain 10); opt-in sim test of protective/warning stops and resume |
| `amcl-persisted-initial-pose`, `rclpy-nonblocking-action-checks`, `odom-twist-from-606c` | Focused unit tests; 606Ch lag measured on a logged run before switching |

### P2: larger or conditional work
| Item | Verification |
|---|---|
| `mls-tpdo7-gyro-stream` + `mls-imu-init-and-axes` (after P0-6 bounds bus-thread work) | `test_canmon` set assertion narrowed deliberately; `test_mls_imu` fake clock; bench (operator, service stopped): write, NMT reset, power cycle, read back 1A06h |
| `odom-calibration-umbmark-scanref` | `tests/test_odocal.py` on synthetic runs; operator runs the square and 360° wall pivots; human edits the profile |
| `rosbag2-replay-regression` + `survey-flight-recorder-slam-replay` (continuous record, map→odom filtered) | Mechanism-level replay tests on trimmed fixtures; one offline slam_toolbox replay of a recorded survey in a sim domain |
| `along-track-goal-checker` (+ `nav2-fault-reporting-plugins` in the same `amr_nav_plugins` package) | Pure picker test; C++ build added to validate.sh ABI check; vehicle endpoint metrics |
| `vector-pursuit-controller` A/B (one alternative controller only) | `test_nav2_params.py` mirrors caps; vehicle cross-track/endpoint comparison |
| `nav2-keepout-filter` | Sim mechanism test: keepout cell lethal in local costmap; executor stop code |
| `dt-raymarch-field` (shared with `edt-sphere-trace-raycast`) | Brute-force oracle equivalence tests; thresholds re-checked on vehicle logs |
| `sick-driver-no-write-fork` (after Safety Designer persistence is proven) | Mock-TCP test: no ChangeCommSettingsCommand with flag false; operator power-cycle check |
| `can-adapter-real-error-counters` (purchase) | Bench session when asked; `ip -d -s link` shows berr counters; bus_health switched to netlink |
| `can-flight-recorder` | Overrun counter shows no tick-jitter increase with it enabled; profile schema + refusal test |
| `cf821-indonesia-band` (regulatory confirmation first) | Profile schema + refusal test; floor read-range check at every stop |
| `bms-decoder-batterystate` (after identification) | Decoder tests on captured payloads; schema + refusal tests; BMS V vs 40A4h plausibility on the vehicle |
| `pmqos-cpu-latency-holder` (only if baseline shows a C8/C10 tail and no thermal rise) | validate.sh env check; one shift of turbostat + wake-lateness comparison |
| `cgroup-scope-sim-tests`, `lichtblick-offline-client-layout`, `snapd`/maintenance-window routine | Fixture self-test; layout opened once on the bench; monthly window logged |

