"""The vehicle ceilings live in route.py; nav2_params.yaml must mirror them, or the
controller could drive at a speed other than the one trackless speed."""

import pathlib

import yaml
from amr_navigation.route import VEHICLE_V_MAX, VEHICLE_W_MAX

PARAMS = pathlib.Path(__file__).resolve().parents[1] / "config" / "nav2_params.yaml"


def test_nav2_ceilings_mirror_route_constants():
    p = yaml.safe_load(PARAMS.read_text())
    follow = p["controller_server"]["ros__parameters"]["FollowPath"]
    spin = p["behavior_server"]["ros__parameters"]
    assert follow["desired_linear_vel"] == VEHICLE_V_MAX
    assert spin["max_rotational_vel"] == VEHICLE_W_MAX
    # RPP's approach ramp is linear in DISTANCE (v = v0 d/D), so its decel demand peaks at
    # v0^2/D right before the floor. A little over the mux decel (base.launch d_max 0.125) is
    # accepted since 2026-11-04: the speed lags the ramp and still reaches the floor in time
    # (test_route_executor_logic.test_approach_ramp_reaches_the_floor_before_the_endpoint).
    d = follow["approach_velocity_scaling_dist"]
    assert VEHICLE_V_MAX**2 / d <= 0.16
    # RPP sees the path only to the costmap's half width: a longer ramp never ends, and every
    # speed runs scaled down ("permanent slowdown", logged by RPP; 3.0 m on a 5 m map, 2026-11-03)
    costmap = p["local_costmap"]["local_costmap"]["ros__parameters"]
    assert d < min(costmap["width"], costmap["height"]) / 2.0
    # the collision check looks about 0.64 m ahead at the ceiling (2026-11-03: 1 m less 33 %)
    assert 0.6 <= follow["max_allowed_time_to_collision_up_to_carrot"] * VEHICLE_V_MAX <= 0.7
