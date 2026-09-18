"""The vehicle ceilings live in route.py; nav2_params.yaml must mirror them, or the
controller could drive faster than a route file is allowed to ask for (or slower than
the boost expects)."""

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
    # v0^2/D right before the floor; that must stay under the mux decel (base.launch d_max 0.5)
    d = follow["approach_velocity_scaling_dist"]
    assert VEHICLE_V_MAX**2 / d <= 0.5
