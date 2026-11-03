# Motion parameters, 2026-11-03

Speed and position are **not** in these logs. Nothing logs the actual velocity, the
commanded velocity or the pose, and no bag was recorded on 2026-11-03. What is here is the
parameter set each session should have run with, for reading next to the step timestamps.

Snapshot taken 15:3x WIB on 2026-11-03. The working tree was then being changed by
another agent (destination buttons, softer auto motion), uncommitted. So "working tree"
means the files as they were at this moment, not necessarily what a given session loaded.

## Which set each session ran

The only parameter the vehicle logs at start is the mux's
(`cmd_mux_kinematics: r=… a_max=… alpha_max=…`, in `../amr-logs/base.log*` and `../ros-log/`):

| Service start | a_max logged | Mux set |
|---|---|---|
| 09:30, 09:42, 10:10, 11:52, 13:08, 13:30, 13:43, 14:30 | 0.300 | HEAD (old) |
| 14:43, 15:10 | 0.200 | working tree (new) |

The mux and drive values below come from `base.launch.py` and load at each service start,
so the table above dates them. The route and executor values (`route.py`, the executor's
parameters) and Nav2's load at each **navigation-layer** start. Nothing in the logs records
which version those were.

## Values

| Parameter | HEAD `71485d9` | Working tree at 15:3x | Where |
|---|---|---|---|
| Straight speed `VEHICLE_V_MAX` / RPP `desired_linear_vel` | 0.60 m/s | 0.60 m/s | `amr_navigation/route.py`, `nav2_params.yaml` |
| Arc (corner) speed | 0.60 m/s, lowered where v/R > 0.9 × 0.45 rad/s | **0.30 m/s** `ARC_V_MPS` | `route.py`, `compiler.arc_speed` |
| Reverse speed | 0.5 × straight | 0.5 × straight | `route.py` `REVERSE_SPEED_RATIO` |
| Spin rate `VEHICLE_W_MAX` | 0.37 rad/s | 0.37 rad/s | `route.py` |
| Arc yaw-rate ceiling `VEHICLE_ARC_W_MAX` | 0.45 rad/s | 0.45 rad/s | `route.py` |
| Auto accel `a_max` | 0.3 m/s² | **0.2 m/s²** | `amr_bringup/launch/base.launch.py` (mux) |
| Auto braking `d_max` | 0.5 m/s² | **0.25 m/s²** | same |
| Auto jerk `auto_jerk` (S-curve) | none | **0.4 m/s³** | same |
| Warning-field braking `field_d_max` | (= d_max 0.5) | 0.5 m/s² | same |
| Angular accel / decel `alpha_max` / `delta_max` | 0.4 / 1.0 rad/s² | 0.4 / 1.0 rad/s² | same |
| Warning field 1 slowdown | × 0.5 over 1 s | × 0.5 over 1 s | `config/scanner_fields.yaml`, logged as `FIELD_WARNING` |
| RPP `approach_velocity_scaling_dist` | 1.0 m | **1.5 m** | `nav2_params.yaml` |
| RPP `max_allowed_time_to_collision_up_to_carrot` | 1.6 s | **1.07 s** | `nav2_params.yaml` |
| Executor `start_gate_m` | 0.10 m | **0.15 m** | `amr_mission/route_executor_node.py` |
| Executor `resume_corridor_m` | (not present) | **0.30 m** | same |
| Route `cross_track_limit_m`, tolerances, spin cap | from the route file | from the route file | `../route/route-itg-02_rev1.yaml` `limits:` |

The full Nav2 file at both revisions is in this folder: `nav2_params.HEAD-71485d9.yaml` and
`nav2_params.working-tree.yaml`.
