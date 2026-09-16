# amr_ws — ROS 2 Humble workspace for the SLAM AMR

Plan: `manuals/slam-generalized-plan/amr_implementation_spec.md` (rev. 2026-09-15:
manual mapping + drawn routes). Status: T1–T8 done in simulation (2026-09-16); T9–T12 hardware next.

## Build, test, run

```bash
cd ~/agv_can/amr_ws
colcon build --symlink-install
source install/setup.bash        # re-source after any build that ADDS a package
colcon test && colcon test-result --verbose          # unit tests only, ~1 min
AMR_SIM_TESTS=1 colcon test --executor sequential    # + the simulation launch tests, ~20 min
ruff check src/                  # ruff.toml here; spec §0.2
```

Launch tests (one per task: T2 square drive, T3 fused odometry, T4 survey,
T5 AMCL, T7 route, T8 run control) are **opt-in** with `AMR_SIM_TESTS=1`:
each runs a full simulation for 1–5 min and four at once starve the N97 into
stale-sensor faults, hence `--executor sequential`. They check *mechanisms*
(does it run, stop, resume, fault); final tolerances are set on hardware.
Each pins its own `ROS_DOMAIN_ID` (61–67) so they can never talk to each other.

`~/.bashrc` sources `/opt/ros/humble` and this overlay, with
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`. A shell started before a package was
added does not see it: `PackageNotFoundError` means re-source, not a bug.
Anything long-lived (`foxglove_bridge`, later systemd units) must be started
from the same overlay, or custom `amr_interfaces` messages will not decode.

| Launch | What |
|---|---|
| `amr_bringup lidar.launch.py` | nanoScan3 driver + URDF TF. Needs UDP 6060: `sudo systemctl stop agv_controller` first |
| `amr_bringup sim.launch.py [slip_noise_std:=0.02] [foxglove:=true]` | fake base + fake IMU → cmd_mux, odom, imu_bias, EKF → URDF; touches no hardware |
| `amr_bringup mapping.launch.py [sim:=true] [maps_dir:=~/amr_maps] [clutter_count:=N] [foxglove:=true]` | sim chain + `scan_synth` + `slam_toolbox` online async + `mapping_session`. `sim:=false` waits for T9/T10 |
| `amr_bringup nav.launch.py [map_id:=sim_factory] [revision:=latest] [maps_dir:=~/amr_maps] [clutter_count:=N] [web:=true] [foxglove:=true]` | verified bundle → `map_server` + AMCL + `localization_monitor` + `controller_server` (RPP) + `behavior_server` (Spin) + `route_executor` + web app; sim chain + `scan_synth` + `fake_panel`. Mutually exclusive with mapping |
| `amr_description description.launch.py [laser_x:=…]` | robot_state_publisher only |

Survey in sim (spec §6.1), from three terminals:
```bash
ros2 launch amr_bringup mapping.launch.py foxglove:=true
ros2 service call /amr/survey/start amr_interfaces/srv/StartSurvey "{map_id: line_section, description: 'floor mark A'}"
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel_teleop   # drive a loop, come back
ros2 service call /amr/survey/returned std_srvs/srv/Trigger      # closure evidence in the reply and /amr/mapping_state
ros2 service call /amr/survey/save amr_interfaces/srv/SaveMap "{note: 'seams ok'}"
```
Foxglove: 3D panel, frame `map`, show `/map`, `/scan`, `/odometry/filtered`. The saved
bundle lands in `<maps_dir>/<map_id>/rev<N>/` (`map.pgm`, `map.yaml`, `posegraph.*`,
`manifest.yaml`). A failed save leaves `.draft-*`, never a `rev*`.

Localise on a saved map (spec §4.2, §4.3):
```bash
ros2 run amr_mission world_bundle ~/amr_maps            # once: the sim world as sim_factory/rev1 (surfaces only)
ros2 launch amr_bringup nav.launch.py clutter_count:=12 foxglove:=true
# Foxglove: 3D panel, frame map; "Publish pose estimate" on /initialpose at the start mark, then drive a little:
ros2 topic echo /amr/localization_state                   # CHECKING -> can_confirm once converged + settled + scan consistent
ros2 service call /amr/localization/confirm std_srvs/srv/Trigger   # operator: scans align -> READY
ros2 service call /sim/set_pose amr_interfaces/srv/SetPose2D "{x_m: 2.0, y_m: 0.0, yaw_rad: 3.14}"  # kidnap test
```

Draw and run a route (spec §5–§7), web app on **http://<robot>:5001**:
1. `/editor`: pick the map, set the start pose (click, drag for heading), add straights (click ahead) and
   turns (CW/CCW 45/90/180/270), **Validate**, **Save revision**, **Create mission**.
2. `/run`: set the initial pose on the map, drive a little, **Confirm** when the scan aligns → READY.
3. Load the mission (READY), selector **AUTO**, physical **Start** → EXECUTING. Pause / Abort /
   Prepare-resume on the page; Start confirms a prepared resume. In sim the panel is
   `ros2 service call /sim/panel/set_mode std_srvs/srv/SetBool "{data: true}"` and
   `ros2 service call /sim/panel/press_start std_srvs/srv/Trigger`; an obstacle is
   `ros2 service call /sim/add_obstacle amr_interfaces/srv/AddObstacle "{x_m: 3, y_m: 0, size_m: 0.6}"`.

Teleop into the sim: `ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel_teleop`
(only under panel MANUAL: the mux takes authority from the panel, never from the command stream).

## Decisions recorded here

**TF tree.** `map → odom → base_footprint → base_link → {laser_frame, imu_frame,
wheel_left, wheel_right}`. The URDF fixes `base_footprint → base_link`, so the
*moving* transform is `odom → base_footprint` (diff_drive_odom now, the EKF from
T3 with `base_link_frame: base_footprint`). Spec §2.3 says "EKF publishes
odom→base_link" and "base_footprint is the parent of base_link" — both cannot
hold, a frame has one parent. `amr_bringup/test/test_sim_tf.py` launches the
composed sim and fails if any frame ever has two.

**Geometry.** Measured 2026-09-15: track 0.487 m (also in `profiles/agv-01.json`),
wheel radius 0.09 m, nanoScan3 0.964 m ahead of the axle with the scan plane
0.110 m above the floor, MLS IMU 0.092 m ahead of the axle. Still `MEASURE`:
chassis box, laser lateral offset and yaw (calibrate against a straight wall).
Still `VERIFY`: IMU lateral/vertical position inside the MLS.

**Repo modules.** ROS nodes reuse `config`, `kinematics` etc. from the repo
root via `amr_base.agv_repo` (bare imports, layer dirs on `sys.path`, same as
`app/server.py`). `AGV_CAN_ROOT` overrides the search. Profile selection is the
controller's `AGV_PROFILE`.

**IMU chain.** `/imu/data_raw` (raw, biased; the MLS node in T10, `fake_imu`
in sim) → `imu_bias_node` → `/imu/data` → EKF, yaw rate only. The bias node
averages stationary samples (stillness from `/wheel_states`, never from the
gyro itself), publishes nothing until the first 2.3 s window completes, and
re-estimates on every later stop; `/imu/recalibrate` discards the estimate.
This replaces `imu_filter_madgwick` (D-3). Measured in sim with the D-3 noise
figures and 2 % wheel slip over an 18 m square: raw odometry 0.5 % / 1.2°,
fused 0.07 % / 0.2°.

**Survey session (T4).** `mapping_session_node` owns IDLE → MAPPING →
RETURN_REVIEW → SAVING → SAVED. Start needs a fresh scan, a calibrated IMU,
still wheels and `map→base_footprint`; it records the start reference from TF.
"Returned" computes closure evidence = current SLAM pose − reference; nothing
forces the pose onto the mark (the sim test injects a real return error and
checks the evidence reports it). Save pauses `slam_toolbox` (its pause service
is a toggle with no state in the reply, so the node tracks it), serialises the
pose graph, writes the occupancy from the last `/map`, hashes everything into
`manifest.yaml`, verifies, then renames staging → `rev<N>` atomically.
Revisions are immutable; a new survey after SAVED/abort needs a relaunch,
because `slam_toolbox` has no reset service in Humble. PGM `free_thresh` is
0.196 so unknown (205) survives a round trip under both loader conventions.

**Localisation readiness (T5).** `localization_monitor_node` runs
`amr_localization/readiness.py`: UNLOCALIZED → CHECKING (on `/initialpose`) →
READY (operator `confirm`, allowed only when converged, settled 2 s, sensors
fresh and the scan consistent) → LOST. Three loss triggers, all sustained 1 s:
a stale stream (§2.4 ages), covariance growth (σ_xy 0.22 m / σ_yaw 10°), and
**scan consistency**: beams *longer* than the saved map allows from the
estimated pose (they pass through mapped walls). Short beams — unmapped clutter
in front of a wall — are ambiguous and only lower the informational
`scan_match`; with 12 clutter boxes it falls to 35 % in the open area while
AMCL stays within 6 cm. The "map→odom jump" trigger (0.15 m / 5°) is measured
**at the robot** (same current odom pose under old and new transform), because a
0.5° yaw correction 20 m from the odom origin moves the frame 17 cm without the
robot moving. AMCL: `likelihood_field_prob` + beam skip, `sigma_hit 0.1`, no
recovery injection — a lost robot stops and is relocalised by the operator.
Measured in sim (12 clutter boxes, 2 % slip, 0.6 m/s): p95 0.06 m / 0.2°;
kidnap detected in < 5 s of motion; recovery to 2 cm after a new initial pose.
The world-as-bundle fixture (`amr_mission.fixtures`) writes **surfaces only**:
a solid map biases the likelihood field toward the obstacle ahead by ~5 cm
along a corridor, which a lidar-built map never has.

**Lidar window (T6+).** The nanoScan3 is a 275° scanner but the mount has a wall
behind it: about **±95°** is usable (operator, 2026-09-16). `scan_synth` defaults
to 190°/381 beams and `nanoscan3.yaml` masks the driver to ±1.658 rad
(VERIFY on the unit that the rear-wall returns are gone). Consequence for
routes: the swept area behind the vehicle is never observed live, so turn
clearance comes from the *saved map* plus the scan's forward window only.

**Routes (T6).** `amr_navigation`: spec §6.4 schema (`route.py`), compiler
(`compiler.py`: straight must lie forward on the current heading within 1 mm,
turns keep their full signed magnitude — CW 270 stays −3π/2), validation
(`validate.py`: map id/revision/**sha256** must match the loaded bundle,
allowed angles, footprint sweeps along every line and the full disc of the
footprint's reach at every pivot, unknown cells blocked, optional
`keepout.yaml` next to the map, `repeat_count` closure), stores
(`<map>/routes/<id>/rev<N>.yaml`, `missions/<id>.yaml` with both hashes).
Footprint: **one file**, `amr_description/config/footprint.yaml` (MEASURE),
read by the validator and injected into the Nav2 local costmap at launch;
margin 0.20 m = cross-track limit 0.10 + localisation allowance 0.10.
`amr_web` (Flask + rclpy adapter, port 5001) serves the maps/survey page, the
canvas editor (map metres persisted, pixel↔world identical to `amr_maps.grid`)
and the run page. No endpoint publishes a velocity.

**Execution (T7).** `route_executor_node` runs one Nav2 action at a time:
`FollowPath` (RPP, `desired_linear_vel 0.30`, no rotate-to-heading, no
reversing, goal checker **0.025 m** — at 0.05 the checker fires the instant it
is inside and every straight ends ~4.5 cm short, which becomes cross-track at
the next corner) and `Spin` (behavior_server, `cmd_vel` remapped to
`/cmd_vel_rotate`, 0.30 rad/s). No planner, no BT: nothing undrawn can move
the vehicle. Checks against the estimated pose: cross-track (limit 0.10 m,
twice that during the first metre while RPP converges), endpoint within
0.08 m / 5° **and** wheels still 0.3 s before advancing, turn travel from the
executor's own unwrapped odometry yaw within 2°, centre drift on odometry
≤ 0.05 m, final map heading within 5° (hardware placeholders: sim AMCL yaw
wanders 1–3° during a spin). A turn's commanded angle folds in the entry heading
error (bounded ±10°) so consecutive turns land on the drawn heading. Measured in sim: straights end within
2 cm, turns within 3°, peak ground-truth cross-track 0.064 m.

**Permission (T7/T8).** The mux (`amr_base.gating`) takes authority from the
**panel** (MANUAL = teleop, AUTO = executor) and the executor's `MotionPermit`
lease (FOLLOW or ROTATE, 0.3 s expiry); a command must also be fresh (0.2 s);
loss of authority zeroes output at once. Executor states IDLE → READY (mission
loaded, localisation READY, start gate 0.10 m / 5°) → EXECUTING on a physical
Start edge under AUTO → PAUSED / BLOCKED (progress kept; `prepare-resume`
re-checks pose, corridor, clearance stable 1 s, sensors, AUTO; Start
continues the *remaining* straight or signed angle) / FAULT (stale wheels,
panel, localisation LOST, `/initialpose` mid-step; `ack` only returns to
IDLE) / DONE. Selector to MANUAL mid-run aborts. Obstruction = scan points in
free map space inside the active step's swept footprint (1.5 m horizon on a
line, the full disc on a turn). Sim panel: `fake_panel_node`; the real adapter
(T12) publishes the same `PanelState`.

**Sim world.** `amr_maps/worlds/sim_factory`: 30 × 20 m, four 16 m rack rows
at y = ±2.4 / ±7.2, start mark (0, 0) at the west end of the B/C aisle.
`scan_synth_node` raycasts it from ground truth with the URDF laser offset,
275°, 551 beams @ 10 Hz by default (configurable up to the wire's 1652),
σ 0.01 m, optional clutter boxes. Survey acceptance: occupied cells agree with
the world > 0.9 both ways at 2-cell tolerance (measured 1.000).

**Acceleration limits.** `cmd_mux` defaults `a_max`/`alpha_max` to
`min(spec, hardware)` where hardware is the profile's 6083h ramp through
`kinematics.max_yaw_accel()` (reconciliation D-1). Parameters can lower them,
never exceed hardware.

**Lidar ownership.** `sick_safetyscanners2` and the controller's
`drivers/lidar.py` both needed `192.168.3.2:6060`; only one could hold it.
Decision 2026-09-15: the ROS driver owns it. The legacy listener, the `/lidar`
page and the zone rail were removed on 2026-09-16; the controller no longer
touches the scanner. The ROS driver writes the scanner's
channel-0 data-output settings over CoLa2; that is not the verified safety
configuration (fields, monitoring cases), which stays humans-only.

**Python environment.** User-site `numpy 2.2.6` + `opencv-python-headless 5.0`
are a consistent pair and are what `amr_tools` (mask painting, T4) will use.
They break `cv_bridge` (system, built on numpy 1.21). Nothing in this project
uses `cv_bridge` — there is no camera (D-4) — so this is a known, accepted
conflict. Do not import `cv_bridge`; if a camera ever appears, revisit.

**ROS domain / DDS scope.** Not yet set. Before the hardware drive node (T9)
exists, sim and hardware must not share a domain: decide `ROS_DOMAIN_ID` and a
CycloneDDS interface config in T11 (deployment).
