# amr_ws — ROS 2 Humble workspace for the SLAM AMR

Plans (historical): `manuals/obsolete/slam-generalized-plan/amr_implementation_spec.md` and
`manuals/obsolete/slam-generalized-plan/unified_amr_service_plan.md`. The unified stack
boots hardware and web in IDLE, then changes mapping/navigation layers under one
supervisor. Software integration through commissioning parity is implemented;
the compact vehicle acceptance and witnessed service cutover remain. Operator
and rollback procedure: [RUNBOOK.md](RUNBOOK.md).

## Build, test, run

```bash
cd ~/agv_can/amr_ws
colcon build --symlink-install
source install/setup.bash        # re-source after any build that ADDS a package
python3 -m pytest -q <affected tests>                 # normal edit: focused fast tests
AMR_SIM_TESTS=1 python3 -m pytest -q src/amr_bringup/test/test_unified_sim.py
                                                     # one milestone workflow, sequential
ruff check src/                  # ruff.toml here; spec §0.2
```

The verification policy is Pareto-based: use focused unit/contract tests for an
ordinary edit and the single unified simulation workflow once per integration
milestone. Older component launch suites remain opt-in for a failure in their
component; do not run all of them by default. Full-stack tests must be
sequential on the N97. Their pinned `ROS_DOMAIN_ID`s keep them isolated.

`~/.bashrc` sources `/opt/ros/humble` and this overlay, with
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`. A shell started before a package was
added does not see it: `PackageNotFoundError` means re-source, not a bug.
Anything long-lived (`foxglove_bridge`, later systemd units) must be started
from the same overlay, or custom `amr_interfaces` messages will not decode.

| Launch | What |
|---|---|
| `python3 -m amr_bringup.supervisor_node --ros-args -p real:=true` | **production topology behind `amr.service`**: persistent base/web/optional Foxglove, IDLE at boot, at most one replaceable mapping/navigation layer, generation leases and bounded process-group cleanup |
| `amr_bringup base.launch.py real:=true\|false [...]` | **the persistent base layer** (unified plan U1): one URDF publisher, mux, odom, imu_bias, EKF; `real:=true` adds drive_node (can0), panel_node (DIO) and the nanoScan3 (`scanner.launch.py`); `real:=false` adds fake base/IMU/panel and optional `scan_synth:=true`. No web, no Foxglove, no SLAM/AMCL. Required nodes end the launch when they exit |
| `amr_bringup mapping_layer.launch.py [maps_dir] [generation:=N] [internal:=true]` | **mode layer**: slam_toolbox + mapping_session only. One survey = one fresh instance |
| `amr_bringup navigation_layer.launch.py map_id:=… revision:=N [generation:=N] [autostart:=false]` | **mode layer**: verified bundle → map_server, AMCL, localization_monitor, controller, behaviors, lifecycle managers, route_executor. One map = one instance |
| `amr_bringup drivers.launch.py [lidar] [pc_loss_ms] [feedback_hz] [gyro_sign] [panel:=real\|fake]` | bench wrapper = `base real:=true` (+ Foxglove). stop `amr.service` first; drive_node/panel_node refuse otherwise (owner lock) |
| `amr_bringup sim.launch.py [slip_noise_std] [scan_synth] [foxglove]` | wrapper = `base real:=false` (+ Foxglove); touches no hardware |
| `amr_bringup mapping.launch.py [sim:=true] [maps_dir] [clutter_count] [foxglove]` | **diagnostics / sim tests only**: base + web + mapping_layer without the supervisor. The web pages need the supervisor's lease and mode (jog, survey start, initial pose and mission controls are refused here); drive with the ROS services and teleop shown below |
| `amr_bringup nav.launch.py [sim:=true] [map_id] [revision] [maps_dir] [clutter_count] [web] [foxglove]` | **diagnostics / sim tests only**: base + web + navigation_layer without the supervisor, same limits. Mutually exclusive with mapping. Interactive operation is `amr.service` (the supervisor) only |
| `amr_bringup lidar.launch.py` | scanner commissioning: `scanner.launch.py` + URDF (+ Foxglove) |
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

## Reference

**TF tree.** `map → odom → base_footprint → base_link → {laser_frame, imu_frame,
wheel_left, wheel_right}`. The URDF fixes `base_footprint → base_link`, so the
*moving* transform is `odom → base_footprint` (diff_drive_odom now, the EKF from
T3 with `base_link_frame: base_footprint`). Spec §2.3 says "EKF publishes
odom→base_link" and "base_footprint is the parent of base_link" — both cannot
hold, a frame has one parent. `amr_bringup/test/test_sim_tf.py` launches the
composed sim and fails if any frame ever has two.

**Geometry.** Measured 2026-09-15: track 0.487 m (also in `profiles/agv-01.json`),
wheel radius 0.09 m, nanoScan3 0.964 m ahead of the axle with the scan plane
0.110 m above the floor, MLS IMU 0.092 m ahead of the axle. Laser yaw and
lateral offset verified 2026-09-16 (decision log, "Lidar commissioning"). Still `MEASURE`:
chassis box. Still `VERIFY`: IMU lateral/vertical position inside the MLS.

**ROS domain / DDS scope (2026-09-16).** Vehicle = `ROS_DOMAIN_ID=10`,
simulation = `20`, launch tests pin 61–67 (`amr_bringup/domains.py`). The shell on
the vehicle sources `env/vehicle.sh` from `~/.bashrc`; for sim work in a shell,
`source ~/agv_can/amr_ws/env/sim.sh`. This is enforced, not advisory:
`drivers.launch.py` (and `mapping`/`nav` with `sim:=false`) refuse any domain but
10; `sim.launch.py` (and `mapping`/`nav` with `sim:=true`) refuse 10 and refuse an
*unset* domain, because default 0 is what every unconfigured ROS host on the LAN
uses. DDS is loopback-only (`config/cyclonedds-local.xml`, `CYCLONEDDS_URI`):
nothing off this host can join either graph, nothing is bound on the Wi-Fi
address, and a sim on this host cannot leak either. Foxglove is unaffected — it
uses `foxglove_bridge` on :8765, not DDS. `lo` has no multicast, so discovery is
unicast over `MaxAutoParticipantIndex` = 120 slots; raise it if a launch ever has
more participants. To let a laptop join deliberately: copy the XML, bind `wlp1s0`,
point `CYCLONEDDS_URI` at the copy for that session only.

Also sourced by anything long-lived: `deploy/amr-supervisor.sh` is the unified
systemd entry point.

How the stack behaves (survey, readiness, execution, permission, panel): README.md
"How it works" and [RUNBOOK.md](RUNBOOK.md) sections 2 and 4. The decisions as they were
made, T1-T12 and U9: `manuals/obsolete/amr_ws-decision-log.md` (historical).
