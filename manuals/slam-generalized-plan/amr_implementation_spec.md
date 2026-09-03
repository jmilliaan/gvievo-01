# AMR Implementation Specification — Coding-Agent Companion to Architecture v1

**Read first:** `amr_slam_architecture.md` (architecture, decisions D1–D8). This document adds the implementation contracts. Where the two conflict, this document wins.
**Safety scope:** PL d / ISO 3691-4 work is explicitly **deferred**. OSSD→STO stays hardwired and outside software. No safety-rated software functions in this phase.

---

## 0. Rules for the Coding Agent (read before writing any code)

### 0.1 Do-not-invent list — parameterize and flag for human verification
| Item | Treatment |
|------|-----------|
| Kinco velocity scaling (DEC factor) | Parameter `vel_dec_per_rad_s`. Default from formula in §3.4 **but flag VERIFY-WITH-EDS in code comment and README**. Never hardcode a literal. |
| Wheel radius, track width | Params `wheel_radius_m`, `track_width_m` with placeholder defaults `0.085`, `0.450` marked `# MEASURE` |
| CAN node IDs | Params; defaults: left drive=1, right drive=2, left encoder=3, right encoder=4 |
| Encoder resolution / multiturn range | Params `enc_counts_per_rev`, `enc_singleturn_bits`, `enc_multiturn_bits` |
| NanoScan3 IP / sensor extrinsics | Params + URDF xacro args, placeholder values marked `# MEASURE` |
| Camera intrinsics | Loaded from `camera_info.yaml` produced by calibration; never inline |
| IMU serial protocol details | Isolated in one parser class; if Yahboom frame format unknown at build time, implement against the documented WitMotion-style 0x55-header frame and flag VERIFY |
| Station map coordinates | Only from `stations.yaml`; never inline |

### 0.2 Conventions
- Python ≥3.12, `rclpy`. One node per file. `ruff` clean, type hints on all public functions.
- Every parameter via `declare_parameter` with explicit type + description string. No module-level mutable state.
- All units SI internally: m, m/s, rad, rad/s, seconds. Unit conversions happen **only** at hardware boundaries (kinco node, encoder node) and are named `*_to_si()` / `si_to_*()`.
- Every node: `--ros-args` friendly, no `time.sleep` in callbacks, timers/executors only. Use `rclpy` MultiThreadedExecutor only where stated (§3.1).
- Logging: `get_logger()`; INFO = state changes only, DEBUG = periodic data, ERROR = faults. No print().
- Frame IDs exactly as §2.3. `frame_id` mismatches are the #1 integration bug class — copy strings from the table.
- Each package ships `test/` with pytest; integration via `launch_testing`. CI target: `colcon test` green with `sim:=true`.

### 0.3 Verification without hardware
The agent has no robot. **All self-verification runs against the sim layer (§8).** Definition of done for every task includes a sim-mode test. Hardware bring-up tasks are marked `[HW]` and end at "code complete + sim-verified + bench checklist written for human".

---

## 1. Workspace Scaffold (exact)

```
amr_ws/src/
├── amr_interfaces/          # custom msgs/srvs (§2.4)
├── amr_description/         # urdf/amr.urdf.xacro, meshes optional
├── amr_base/
│   ├── amr_base/kinco_drive_node.py
│   ├── amr_base/wheel_encoder_node.py
│   ├── amr_base/diff_drive_odom_node.py
│   ├── amr_base/cmd_mux_kinematics_node.py
│   └── amr_base/canopen_common.py        # shared NMT/SDO/PDO helpers
├── amr_localization/
│   ├── amr_localization/qr_pose_node.py
│   ├── config/ekf.yaml
│   └── config/amcl.yaml
├── amr_navigation/
│   ├── config/nav2_params.yaml
│   ├── config/keepout_params.yaml, speed_params.yaml
│   └── behavior_trees/navigate_w_recovery.xml
├── amr_mission/
│   ├── amr_mission/mission_executor_node.py
│   ├── amr_mission/precision_align_node.py
│   └── config/stations.yaml, missions/
├── amr_sim/                 # §8 — fake HAL, scan synthesizer, fake QR
├── amr_bringup/
│   ├── launch/drivers.launch.py, mapping.launch.py, nav.launch.py, sim.launch.py
│   ├── config/can.yaml
│   └── systemd/amr.service, amr-can.service
├── amr_maps/                # versioned artifacts (git-tagged), sample test map included
└── amr_tools/               # qr_survey.py, calib helpers, mask_paint.py
```

---

## 2. Interface Contracts

### 2.1 Topic contract table (authoritative)

| Topic | Type | Publisher | Subscribers | Rate | QoS |
|-------|------|-----------|-------------|------|-----|
| `/cmd_vel` | geometry_msgs/Twist | nav2 controller_server | cmd_mux | 20 Hz | Reliable, depth 1 |
| `/cmd_vel_teleop` | geometry_msgs/Twist | teleop | cmd_mux | var | Reliable, depth 1 |
| `/cmd_wheel_vel` | amr_interfaces/WheelVelocities | cmd_mux | kinco_drive_node, sim fake_base | 50 Hz | Reliable, depth 1 |
| `/wheel_states` | amr_interfaces/WheelStates | wheel_encoder_node (or sim) | diff_drive_odom | 100 Hz | SensorData |
| `/odom_raw` | nav_msgs/Odometry | diff_drive_odom | ekf_local | 100 Hz | SensorData |
| `/odometry/filtered` | nav_msgs/Odometry | ekf_local | nav2, mission | 50 Hz | SensorData |
| `/imu/data_raw` | sensor_msgs/Imu | imu_node | madgwick | ≥100 Hz | SensorData |
| `/imu/data` | sensor_msgs/Imu | madgwick | ekf_local | ≥100 Hz | SensorData |
| `/scan` | sensor_msgs/LaserScan | sick driver (or sim) | slam_toolbox / amcl / costmaps | ~25 Hz | SensorData |
| `/scan/field_status` | amr_interfaces/SafetyFieldStatus | sick driver | diagnostics, mission | 10 Hz | Reliable, depth 1 |
| `/floor_cam/image_raw` | sensor_msgs/Image | camera node (or sim) | qr_pose_node | 15 fps | SensorData |
| `/qr/detections` | amr_interfaces/QrDetection | qr_pose_node | mission, precision_align | event | Reliable, depth 5 |
| `/qr/pose` | geometry_msgs/PoseWithCovarianceStamped | qr_pose_node | (logged; gated relay to /initialpose) | event | Reliable, depth 1 |
| `/initialpose` | PoseWithCovarianceStamped | qr_pose_node (gated, §6.3) / Foxglove | amcl | event | Reliable, depth 1 |
| `/drives/status` | amr_interfaces/DriveStatus | kinco_drive_node | diagnostics, mission | 10 Hz | Reliable, depth 1 |
| `/diagnostics` | diagnostic_msgs/DiagnosticArray | all HW nodes | aggregator | 1 Hz | default |

QoS shorthand: SensorData = best-effort, volatile, depth 5. Reliable = reliable, volatile, stated depth.

### 2.2 Action/service usage
| Interface | Type | Client → Server |
|-----------|------|-----------------|
| `/navigate_to_pose` | nav2_msgs/action/NavigateToPose | mission_executor → bt_navigator |
| `/amr/enable_drives`, `/amr/clear_faults` | std_srvs/Trigger | mission/UI → kinco_drive_node |
| `/amr/run_mission`, `/amr/pause`, `/amr/abort` | amr_interfaces/srv/RunMission, std_srvs/Trigger | UI/CLI → mission_executor |

### 2.3 Frames (exact strings)
`map`, `odom`, `base_link`, `base_footprint` (z=0 projection, parent of base_link), `laser_frame`, `imu_frame`, `floor_cam_frame`. EKF publishes `odom→base_link`; AMCL publishes `map→odom`; everything else static from URDF.

### 2.4 Custom messages (`amr_interfaces`)
```
WheelVelocities.msg : std_msgs/Header header; float64 left_rad_s; float64 right_rad_s
WheelStates.msg     : header; float64 left_pos_rad; float64 right_pos_rad;
                      float64 left_vel_rad_s; float64 right_vel_rad_s; bool left_valid; bool right_valid
DriveStatus.msg     : header; uint16 left_statusword; uint16 right_statusword;
                      uint16 left_error_code; uint16 right_error_code;
                      string left_state; string right_state; bool operational
SafetyFieldStatus.msg: header; bool protective_field_clear; bool warning_field_clear; uint8 active_monitoring_case
QrDetection.msg     : header; string code_text; geometry_msgs/Pose camera_to_code;
                      float64 reproj_error_px; bool pose_valid
srv/RunMission.srv  : string mission_id --- bool accepted; string message
```

---

## 3. Node Implementation Specs — `amr_base`

### 3.1 `kinco_drive_node.py` [HW]
- **Stack:** `python-canopen` over SocketCAN `can0` @ 1 Mbps. Single node manages both drives. MultiThreadedExecutor (CAN RX thread + ROS callbacks).
- **Startup sequence (per drive):**
  1. NMT reset-communication → wait boot-up heartbeat.
  2. SDO configure: mode of operation `0x6060 = 3` (Profile Velocity); heartbeat producer `0x1017 = 200 ms`; verify PDO mapping (§3.3) — reconfigure via SDO if EDS defaults differ; profile accel/decel `0x6083/0x6084` from params.
  3. NMT start (operational).
  4. CiA-402 enable: controlword `0x0006` → `0x0007` → `0x000F`, verifying statusword after each step (masks §3.2), 500 ms timeout per transition → ERROR + retry policy (3 attempts → FAULT state, publish DriveStatus, require `/amr/clear_faults`).
- **Runtime:** subscribe `/cmd_wheel_vel`; 50 Hz timer writes RPDO1 (controlword 0x000F + target velocity 0x60FF). **Command watchdog:** if no `/cmd_wheel_vel` for 200 ms → write zero velocity; after a further 2 s → transition to Switched-On (torque hold per drive config) and log.
- **Feedback:** TPDO callbacks update statusword/actual-velocity; publish `/drives/status` 10 Hz. EMCY frames → ERROR log + DriveStatus error_code.
- **Fault handling:** statusword fault bit → controlword `0x0080` reset only via `/amr/clear_faults` service (never auto-reset).

### 3.2 CiA-402 statusword decode (use exactly)
| State | statusword & mask == value |
|-------|---------------------------|
| Not ready | & 0x004F == 0x0000 |
| Switch-on disabled | & 0x004F == 0x0040 |
| Ready to switch on | & 0x006F == 0x0021 |
| Switched on | & 0x006F == 0x0023 |
| Operation enabled | & 0x006F == 0x0027 |
| Fault | & 0x004F == 0x0008 |
| Quick stop active | & 0x006F == 0x0007 |

### 3.3 PDO mapping (per drive)
| PDO | Content | Bytes | Transmission |
|-----|---------|-------|--------------|
| RPDO1 | 0x6040 ctrlword (u16) + 0x60FF target vel (i32) | 6 | async |
| TPDO1 | 0x6041 statusword (u16) + 0x606C actual vel (i32) | 6 | event-timer 10 ms (type 254/255) |
| TPDO2 | 0x603F error (u16) + 0x6061 mode display (i8) | 3 | on change |

No SYNC producer required for velocity mode (simpler than positional). If Kinco FD requires SYNC for TPDO, switch TPDO1 to type 1 and add a 100 Hz SYNC producer in `canopen_common.py` — keep both behind param `use_sync`.

### 3.4 Kinco unit conversion (VERIFY-WITH-EDS)
Kinco FD velocity object 0x60FF uses internal DEC units. Documented formula:
```python
# DEC = rpm * 512 * encoder_resolution / 1875   (Kinco FD family)  # VERIFY against FD EDS
def rad_s_to_dec(w: float, enc_res: int) -> int:
    rpm = w * 60.0 / (2.0 * math.pi)
    return int(rpm * 512 * enc_res / 1875)
```
Wrap in class `KincoScaler`, unit-test with known pairs, expose `vel_dec_per_rad_s` override param. Mind sign convention: right wheel typically inverted (`right_invert: true` param).

### 3.5 `wheel_encoder_node.py` [HW]
- CiA-406 encoders, position object `0x6004` (u32) via TPDO @ 100 Hz (event-timer 10 ms).
- **Wrap-safe delta:** `d = ((new - old + H) % R) - H` with `R = 2^bits`, `H = R // 2`.
- Velocity: filtered differentiation — delta/dt through 1st-order LPF, `vel_lpf_cutoff_hz` param (default 20).
- Staleness: per-wheel `*_valid = false` if no TPDO for 50 ms; odom node must then hold last command-free estimate and raise diagnostics WARN.
- Publishes `/wheel_states` with positions in rad at the **wheel** (apply external-encoder mounting ratio param `enc_to_wheel_ratio`, default 1.0).

### 3.6 `diff_drive_odom_node.py`
```python
v  = r * (w_r + w_l) / 2.0
wz = r * (w_r - w_l) / track
th_mid = th + wz * dt / 2.0          # midpoint integration
x += v * dt * cos(th_mid); y += v * dt * sin(th_mid); th += wz * dt
```
- Inputs: `/wheel_states` deltas (positions, not velocities — integrate counts, derive twist for the message).
- Covariance (Odometry): pose cov grows with distance — set twist cov static: `vx 1e-3, vy 1e6 (unused), vyaw 1e-3`; pose cov values large/unused since EKF consumes twist+pose increments. Param-exposed.
- Does **not** publish TF (EKF owns `odom→base_link`). Param `publish_tf` default false for standalone tests.

### 3.7 `cmd_mux_kinematics_node.py`
- Priority: teleop > nav. Teleop active = message within 500 ms.
- Slew limiting: accel `a_max` (default 0.5 m/s²), `alpha_max` (1.0 rad/s²) applied on v, ω before inverse kinematics.
- Inverse kinematics: `w_l = (v − ω·track/2)/r`, `w_r = (v + ω·track/2)/r`; clamp to `wheel_vel_max_rad_s`, scale v and ω jointly to preserve curvature when clamping.
- Output zero if no input within 200 ms (defense-in-depth with drive node watchdog).

---

## 4. State Estimation Configs

### 4.1 `ekf.yaml` (robot_localization, copy-paste baseline)
```yaml
ekf_local:
  ros__parameters:
    frequency: 50.0
    two_d_mode: true
    publish_tf: true
    map_frame: map
    odom_frame: odom
    base_link_frame: base_link
    world_frame: odom
    odom0: /odom_raw
    odom0_config: [false, false, false,   # x y z
                   false, false, false,   # r p y
                   true,  false, false,   # vx vy vz
                   false, false, true,    # vr vp vyaw
                   false, false, false]
    odom0_differential: false
    imu0: /imu/data
    imu0_config: [false, false, false,
                  false, false, false,
                  false, false, false,
                  false, false, true,     # yaw rate only (hobby-grade IMU policy)
                  false, false, false]
    imu0_remove_gravitational_acceleration: true
```

### 4.2 `amcl.yaml` key values (rest = nav2 defaults)
```yaml
amcl:
  ros__parameters:
    z_hit: 0.7
    z_rand: 0.25
    z_short: 0.025
    z_max: 0.025
    laser_likelihood_max_dist: 2.0
    do_beamskip: true
    min_particles: 500
    max_particles: 2000
    update_min_d: 0.05
    update_min_a: 0.03
    alpha1: 0.1   # rot->rot
    alpha2: 0.1   # trans->rot
    alpha3: 0.1   # trans->trans
    alpha4: 0.1   # rot->trans
    resample_interval: 2
    transform_tolerance: 0.3
    set_initial_pose: false
```

### 4.3 IMU chain
- `imu_node`: serial parser (frame-format class isolated per §0.1); startup gyro-bias calibration: average 2 s of stationary samples, subtract; refuse to publish `/imu/data_raw` until calibrated; service `/imu/recalibrate`.
- `imu_filter_madgwick`: `use_mag: false`, `world_frame: enu`, gain 0.1.

---

## 5. nav2 Configuration (`nav2_params.yaml` deltas from defaults)

| Section | Setting | Value |
|---------|---------|-------|
| controller_server | plugin | RegulatedPurePursuitController |
| RPP | desired_linear_vel | 0.6 |
| RPP | lookahead (min/max/use_velocity_scaled) | 0.3 / 0.9 / true |
| RPP | regulated_linear_scaling_min_radius | 0.9 |
| RPP | use_collision_detection | true |
| planner_server | plugin | SmacPlanner2D |
| global_costmap | plugins | static, obstacle, inflation + filters: keepout, speed |
| local_costmap | size / resolution | 5×5 m rolling / 0.05 |
| both costmaps | obstacle layer source | `/scan`, raytrace 8 m, obstacle 6 m |
| inflation | radius / cost_scaling | 0.55 / 3.0 |
| footprint | rectangle from URDF dims, param-shared | `# MEASURE` |
| bt_navigator | default BT | behavior_trees/navigate_w_recovery.xml |
| velocity_smoother | max v/a | match mux limits |

BT file: stock `navigate_to_pose_w_replanning_and_recovery.xml` copied in-repo and trimmed: recoveries = clear-costmap → spin(0.5 rad) → backup(0.15 m) → fail. No invented BT nodes.

---

## 6. QR Subsystem

### 6.1 `qr_pose_node.py`
Pipeline per frame: undistort (intrinsics from `camera_info.yaml`) → `zxing-cpp` detect+decode → corner refinement (cv2.cornerSubPix) → `solvePnP` (IPPE_SQUARE, code physical size param `code_size_m`, default 0.10) → `camera_to_code` pose → publish `/qr/detections`.
Pose validity gates: reprojection error < 1.5 px, all 4 corners ≥ 10 px from image edge, decode string matches `^STN-[A-Z0-9]{4}$` or `^WPT-[A-Z0-9]{4}$`.

### 6.2 Map-pose computation
`T_map_base = T_map_code · inv(T_cam_code) · inv(T_base_cam)` — `T_map_code` from `stations.yaml`; `T_base_cam` from TF static. Publish `/qr/pose` with covariance diag `[1e-4, 1e-4, ., ., ., 3e-4]`.

### 6.3 AMCL injection policy (gated relay)
Relay `/qr/pose` → `/initialpose` **only when all true:** robot speed < 0.05 m/s; detection stable ≥ 5 consecutive frames; distance between QR pose and AMCL pose > 0.05 m or yaw > 1° (i.e., only correct when there is meaningful error); rate-limited 1 per 10 s. Otherwise QR is observation-only. This prevents particle-filter whiplash mid-motion.

### 6.4 `precision_align_node.py`
Action `AlignToCode` (goal: code_text, target offset pose): P-controller on lateral + heading + longitudinal error from `/qr/detections`, gains `kp_lin 0.8 / kp_ang 1.5`, output clamped 0.08 m/s / 0.3 rad/s on `/cmd_vel_teleop` priority channel; success: |err| < 5 mm & < 0.5° for 1 s; abort if code lost > 1 s.

### 6.5 `stations.yaml` schema
```yaml
stations:
  - id: STN-A001
    code_text: STN-A001
    map_pose:   {x: 12.340, y: 4.560, yaw_deg: 90.0}   # from qr_survey.py
    approach:   {x: 12.340, y: 5.560, yaw_deg: -90.0}  # nav2 goal
    align_offset: {x: 0.0, y: 0.0, yaw_deg: 0.0}
    tolerance_mm: 10
```

---

## 7. Mission Executor

### 7.1 FSM (explicit, no library needed)
States: `IDLE → MISSION_LOADED → NAVIGATING → ALIGNING → AT_STATION → (next leg | DONE)`; orthogonal: `PAUSED`, `FAULT`.
Transitions:
| From | Event | To | Action |
|------|-------|----|--------|
| IDLE | RunMission(id) | MISSION_LOADED | load+validate YAML against stations.yaml |
| MISSION_LOADED | auto | NAVIGATING | send NavigateToPose(approach) |
| NAVIGATING | nav SUCCEEDED & station has code | ALIGNING | send AlignToCode |
| NAVIGATING | nav SUCCEEDED & waypoint only | AT_STATION | dwell timer |
| NAVIGATING | nav ABORTED | FAULT(retryable) | retry ≤ 2 with 5 s backoff, then FAULT |
| ALIGNING | success | AT_STATION | verify code_text == expected (sequence check); mismatch → FAULT |
| AT_STATION | dwell/handshake done | NAVIGATING(next) or DONE | — |
| any | Pause srv | PAUSED | cancel nav action, zero cmd |
| PAUSED | Resume | re-enter prior state | re-send goal |
| any | drive fault / field not clear > 10 s | FAULT | requires operator clear |

### 7.2 Mission file schema
```yaml
mission_id: M001
loop: false
legs:
  - station: STN-A001
    action: dwell        # dwell | handshake_stub
    dwell_s: 3
  - station: WPT-0007
```

---

## 8. Sim / Mock Layer (`amr_sim`) — agent's test harness

Launch arg `sim:=true` swaps **only Layer-1 nodes**; every interface above is byte-identical.

| Sim node | Replaces | Behavior |
|----------|----------|----------|
| `fake_base_node` | kinco + encoder + odom source | Subscribes `/cmd_wheel_vel`; integrates perfect kinematics + configurable slip noise; publishes `/wheel_states`, ground-truth `/sim/ground_truth` (Odometry) |
| `scan_synth_node` | sick driver | Raycasts NanoScan3 geometry (275°, 0.39° step, 25 Hz) against the loaded map PGM from ground-truth pose; adds Gaussian range noise σ=0.01 m; optional clutter: N random rectangles injected to emulate pallets (`clutter_count` param) — this is how AMCL robustness (§4.2) gets regression-tested |
| `fake_imu_node` | imu chain | Yaw rate from ground truth + bias-random-walk noise |
| `fake_qr_node` | camera + qr_pose | Emits QrDetection when ground-truth pose within FOV of any station in stations.yaml, with configurable pixel noise |

Included test assets: `amr_maps/sim_factory/` — a 30×20 m synthetic plant-section map (agent generates programmatically: walls, 3 aisles, 6 stations) + stations.yaml + missions.

**Mandatory integration tests (launch_testing, sim mode):**
1. `test_odom_accuracy`: drive square 4×5 m via scripted cmd_vel → fused odom vs ground truth < 1 % distance error.
2. `test_localization_clutter`: AMCL converged pose error < 0.10 m / 2° over a mission with `clutter_count: 12`.
3. `test_nav_ab`: 20 consecutive A↔B navigations, zero failures, no keepout violation (check ground-truth trace against mask).
4. `test_qr_injection_gating`: QR corrections only fire when stationary; AMCL pose jump bounded.
5. `test_mission_fsm`: full mission incl. injected nav abort → retry → success; injected wrong-code → FAULT.
6. `test_watchdogs`: kill cmd stream → wheel vel zero within 250 ms (fake_base asserts).

---

## 9. Bringup / Launch Contracts

| Launch file | Includes | Args |
|-------------|----------|------|
| `drivers.launch.py` | Layer-1 real HW nodes + EKF + imu chain + robot_state_publisher | `can_if:=can0` |
| `sim.launch.py` | amr_sim nodes + EKF + robot_state_publisher | `world:=sim_factory clutter_count:=N` |
| `mapping.launch.py` | (drivers or sim) + slam_toolbox sync + foxglove_bridge | `sim:=bool` |
| `nav.launch.py` | (drivers or sim) + map_server + AMCL + nav2 + qr + mission + foxglove_bridge | `sim:=bool map:=<tag>` |

systemd: `amr-can.service` (ip link setup, oneshot) → `amr.service` (nav.launch, Restart=on-failure, After=amr-can).

---

## 10. Agent Task Plan (implement in this order; each task = PR-sized)

| # | Task | Done criteria |
|---|------|---------------|
| T1 | `amr_interfaces`, `amr_description` URDF, workspace builds | `colcon build` clean; TF tree renders |
| T2 | `amr_sim.fake_base_node` + cmd_mux + diff_drive_odom | unit tests for kinematics/wrap math; sim square-drive odom test passes |
| T3 | EKF + fake_imu integration | test_odom_accuracy green |
| T4 | scan_synth + map gen tool + slam_toolbox mapping profile | map produced from sim teleop run matches generated world (visual + occupancy IoU > 0.9) |
| T5 | AMCL + nav.launch sim profile | test_localization_clutter green |
| T6 | nav2 config + BT + keepout/speed masks | test_nav_ab green |
| T7 | qr_pose_node + fake_qr + injection relay + precision_align | tests 4 green; align converges in sim |
| T8 | mission_executor + stations/missions schemas + CLI (`amr mission run M001`) | test_mission_fsm green |
| T9 | `kinco_drive_node` + `wheel_encoder_node` + canopen_common `[HW]` | unit tests with mocked canopen bus (python-canopen supports virtual bus `vcan`/`virtual` — use it); bench checklist doc generated |
| T10 | imu serial driver `[HW]`, sick driver config, camera calib procedure docs | parser unit-tested against captured frame fixtures; configs reviewed |
| T11 | systemd, diagnostics aggregation, README runbooks (survey workflow §6.1 of arch doc) | clean-boot sim soak 1 h, diagnostics OK |

Human-in-the-loop gates: after T9 (before powered bench test), after T11 (before first floor run). Everything else the agent self-verifies in sim.

---

## 11. Open Items Deliberately Deferred
- Safety-rated functions, monitoring-case switching, PL d argumentation — later phase (ties into your existing FX3/NanoScan3 tow-tractor safety architecture).
- Fleet/MQTT/VDA5050 adapter — interface stub only (`fleet_adapter` package reserved, not created).
- Elevated nav LiDAR — config remap documented in arch doc §6.2, no code now.
- Battery/power telemetry — your scope; reserve `/power/state` topic name.
