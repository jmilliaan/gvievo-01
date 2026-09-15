# amr_ws — ROS 2 Humble workspace for the SLAM AMR

Plan: `manuals/slam-generalized-plan/`. Task numbering (T1…) is spec §10 with the
reconciliation §4 deltas. Status: T1, T2, T3 done (2026-09-15).

## Build, test, run

```bash
cd ~/agv_can/amr_ws
colcon build --symlink-install
source install/setup.bash        # re-source after any build that ADDS a package
colcon test && colcon test-result --verbose
ruff check src/                  # ruff.toml here; spec §0.2
```

`~/.bashrc` sources `/opt/ros/humble` and this overlay, with
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`. A shell started before a package was
added does not see it: `PackageNotFoundError` means re-source, not a bug.
Anything long-lived (`foxglove_bridge`, later systemd units) must be started
from the same overlay, or custom `amr_interfaces` messages will not decode.

| Launch | What |
|---|---|
| `amr_bringup lidar.launch.py` | nanoScan3 driver + URDF TF. Needs UDP 6060: `sudo systemctl stop agv_controller` first |
| `amr_bringup sim.launch.py [slip_noise_std:=0.02] [foxglove:=true]` | fake base + fake IMU → cmd_mux, odom, imu_bias, EKF → URDF; touches no hardware |
| `amr_description description.launch.py [laser_x:=…]` | robot_state_publisher only |

Teleop into the sim: `ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel_teleop`.

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

**Acceleration limits.** `cmd_mux` defaults `a_max`/`alpha_max` to
`min(spec, hardware)` where hardware is the profile's 6083h ramp through
`kinematics.max_yaw_accel()` (reconciliation D-1). Parameters can lower them,
never exceed hardware.

**Lidar ownership.** `sick_safetyscanners2` and the controller's
`drivers/lidar.py` both need `192.168.3.2:6060`; only one can hold it. Decision
2026-09-15: the ROS driver owns it, the legacy listener is to be removed. Until
it is, the `/lidar` page shows *assumed occupied* while `lidar.launch.py` runs —
that is its fail-safe, not a fault. The ROS driver writes the scanner's
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
