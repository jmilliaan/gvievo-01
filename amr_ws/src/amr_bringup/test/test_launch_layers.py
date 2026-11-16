"""U1 gate (unified plan): launch layers are separable and mode layers are clean.

Static: each launch file is loaded and its entity tree walked with a stub
context, without starting processes or a ROS graph. What this proves is
composition - which executables each entry point can spawn - not runtime
behaviour (that is P7's sequential simulation).
"""

from __future__ import annotations

import os

import pytest
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
    RegisterEventHandler,
    TimerAction,
)
from launch.launch_description_sources import get_launch_description_from_any_launch_file
from launch_ros.actions import Node

from amr_bringup import domains

LAUNCH = os.path.join(get_package_share_directory("amr_bringup"), "launch")
BASE_EXES = {
    "cmd_mux_kinematics_node",
    "scan_gate_node",
    "ekf_node",
    "robot_state_publisher",
    "event_recorder_node",  # WP-H3, real and sim
}
# rfid_node only with rfid.enabled (decision 23: false on both units, 2026-11-16)
HW_EXES = {"drive_node", "panel_node", "sick_safetyscanners2_node"}
# diff_drive_odom and imu_bias are sim only since WP-C5/C10 (2026-11-16): on the vehicle drive_node
# publishes /odom_raw and /imu/data itself, so a second publisher there would fight it.
SIM_EXES = {"fake_base_node", "fake_imu_node", "fake_panel_node", "scan_synth_node",
            "diff_drive_odom_node", "imu_bias_node"}
MAPPING_EXES = {"async_slam_toolbox_node", "mapping_session_node", "survey_move_node"}
LINE_EXES = {"line_follow_node"}
NAV_EXES = {
    "map_server",
    "amcl",
    "lifecycle_manager",
    "localization_monitor_node",
    "controller_server",
    "behavior_server",
    "route_executor_node",
}


def _text(x, context) -> str:
    if isinstance(x, str):
        return x
    if hasattr(x, "perform"):
        return x.perform(context)
    return "".join(_text(i, context) for i in x)


def _walk(entities, context, out: dict, depth=0):
    """Collect executables and included files. Conditions are ignored: this is
    'what CAN this launch spawn', which is the stricter question."""
    for e in entities:
        if isinstance(e, DeclareLaunchArgument):
            if e.name not in context.launch_configurations and e.default_value is not None:
                context.launch_configurations[e.name] = "".join(s.perform(context) for s in e.default_value)
            continue
        if isinstance(e, Node):
            exe = e.node_executable
            exe = "".join(s.perform(context) for s in exe) if isinstance(exe, list) else str(exe)
            out.setdefault("exes", []).append(exe)
            out.setdefault("nodes", []).append((exe, e))
            out.setdefault("params", {})[exe] = list(e._Node__parameters or [])
            out.setdefault("remaps", {})[exe] = [
                (_text(a, context), _text(b, context)) for a, b in (e._Node__remappings or [])
            ]
            continue
        if isinstance(e, ExecuteProcess):  # a plain process (the black box); Node is caught above
            cmd = getattr(e, "process_description", e).cmd
            out.setdefault("procs", []).append((e, [_text(c, context) for c in cmd]))
            continue
        if isinstance(e, IncludeLaunchDescription):
            raw = e.launch_description_source._LaunchDescriptionSource__location  # unexpanded substitutions
            path = "".join(s.perform(context) for s in raw) if not isinstance(raw, str) else raw
            out.setdefault("includes", []).append(os.path.basename(path))
            sub_ctx = LaunchContext()
            sub_ctx.launch_configurations.update(context.launch_configurations)
            for k, v in e.launch_arguments:
                sub_ctx.launch_configurations[_text(k, context)] = _text(v, context)
            if path.endswith(".py"):
                sub = get_launch_description_from_any_launch_file(path)
                _walk(sub.entities, sub_ctx, out, depth + 1)
            continue
        if isinstance(e, OpaqueFunction):
            fn, a, kw = e._OpaqueFunction__function, e._OpaqueFunction__args, e._OpaqueFunction__kwargs
            produced = fn(context, *a, **kw)
            _walk(produced or [], context, out, depth + 1)
            continue
        if isinstance(e, TimerAction):
            _walk(e.actions, context, out, depth + 1)
            continue
        if isinstance(e, RegisterEventHandler):
            out["handlers"] = out.get("handlers", 0) + 1
            # the action an OnProcessExit watches (private in Humble: found by type)
            out.setdefault("watched", []).extend(
                v for v in vars(e.event_handler).values() if isinstance(v, Node)
            )
            continue
        if isinstance(e, LaunchDescription):
            _walk(e.entities, context, out, depth + 1)


def compose(name: str, **args) -> dict:
    ld = get_launch_description_from_any_launch_file(os.path.join(LAUNCH, name))
    ctx = LaunchContext()
    ctx.launch_configurations.update({k: str(v) for k, v in args.items()})
    out: dict = {}
    _walk(ld.entities, ctx, out)
    out.setdefault("exes", [])
    out.setdefault("includes", [])
    return out


@pytest.fixture(autouse=True)
def sim_domain(monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.SIM))


def test_mapping_layer_is_only_slam_and_coordinator():
    c = compose("mapping_layer.launch.py")
    assert set(c["exes"]) == MAPPING_EXES
    assert c["includes"] == []
    assert c["handlers"] == 2  # slam and the session are required; survey_move is not


def test_line_layer_is_only_the_follower(tmp_path, monkeypatch):
    # generation and real are the ONLY arguments _start_line passes; anything
    # else required here would make the supervisor's spawn fail as SPAWN_FAILED.
    # Without a map selected (2026-11-16 triage: the test read the live ~/.amr, where the
    # vehicle has line_graph.json, so tape localization added map_server/AMCL/monitor). The
    # with-a-map case is test_both_layers_build_the_localization_group_once.
    from agv_core import paths  # noqa: PLC0415

    monkeypatch.setenv(paths.STATE_ENV, str(tmp_path / "state"))
    monkeypatch.setenv(paths.MAPS_ENV, str(tmp_path / "maps"))
    c = compose("line_layer.launch.py", generation=3, real="true")
    assert set(c["exes"]) == LINE_EXES
    assert c["includes"] == []
    assert c["handlers"] == 1  # the follower is required: no follower, no layer
    # The mux of generation 3 subscribes to the generation-private line_cmd
    # topic; the follower must publish there or the mux never sees a command.
    assert c["remaps"]["line_follow_node"] == [("/amr/line_cmd", "/amr/layers/g3/amr/line_cmd")]
    params = [_param_dict(p) for p in c["params"]["line_follow_node"] if isinstance(p, dict)]
    assert any(p.get("field_source") == "scanner" for p in params)
    assert any(str(p.get("loc_status", "")).startswith("off:") for p in params)  # and says why


def test_line_layer_assumes_the_field_clear_only_in_sim():
    """The sim has no scanner. A vehicle launch must never carry assume_clear:
    there a stale /output_paths is UNKNOWN and the layer refuses to arm."""
    c = compose("line_layer.launch.py", generation=3, real="false")
    params = [_param_dict(p) for p in c["params"]["line_follow_node"] if isinstance(p, dict)]
    assert any(p.get("field_source") == "assume_clear" for p in params)
    d = compose("line_layer.launch.py", generation=3)  # default = real
    params = [_param_dict(p) for p in d["params"]["line_follow_node"] if isinstance(p, dict)]
    assert any(p.get("field_source") == "scanner" for p in params)


def test_navigation_layer_has_no_base_web_or_sim(tmp_path):
    # needs a verified bundle to compose; use the world fixture
    from amr_mission.fixtures import write_world_as_bundle  # noqa: PLC0415

    write_world_as_bundle(str(tmp_path))
    c = compose("navigation_layer.launch.py", maps_dir=str(tmp_path), map_id="sim_factory")
    assert set(c["exes"]) == NAV_EXES
    assert not (set(c["exes"]) & (BASE_EXES | HW_EXES | SIM_EXES | {"web_node"}))
    assert c["includes"] == []
    assert c["handlers"] == 8  # every node, the two lifecycle managers too since WP-H4


def test_scanner_layer_has_no_description():
    c = compose("scanner.launch.py")
    assert c["exes"] == ["sick_safetyscanners2_node"] and c["includes"] == []


def test_scanner_driver_respawns():
    """It aborts when the scanner is unreachable at start; a cable plugged in later must recover."""
    ld = get_launch_description_from_any_launch_file(
        os.path.join(get_package_share_directory("amr_bringup"), "launch", "scanner.launch.py")
    )
    nodes = [e for e in ld.entities if isinstance(e, Node)]
    # launch keeps these private (ExecuteLocal); no public getter in Humble
    assert len(nodes) == 1 and nodes[0]._ExecuteLocal__respawn is True
    assert nodes[0]._ExecuteLocal__respawn_delay > 0


def test_sim_base_is_fakes_plus_estimation_and_one_description():
    c = compose("base.launch.py", real="false")
    assert set(c["exes"]) == SIM_EXES | BASE_EXES
    assert c["exes"].count("robot_state_publisher") == 1
    assert not (set(c["exes"]) & (HW_EXES | MAPPING_EXES | NAV_EXES | {"web_node"}))


def test_real_base_composes_hardware_once(monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.VEHICLE))
    c = compose("base.launch.py", real="true")
    # fake_panel is conditional (panel:=fake); this walk ignores conditions
    assert set(c["exes"]) == HW_EXES | BASE_EXES | {"fake_panel_node"}
    assert c["exes"].count("robot_state_publisher") == 1  # the scanner include no longer brings a second one
    assert c["includes"].count("scanner.launch.py") == 1
    assert "web_node" not in c["exes"]


def test_off_base_launches_todays_nodes(monkeypatch):
    """Station plan: the switch off and no rear lidar is the list before the plan, real and sim."""
    from agv_core import config
    monkeypatch.setattr(config, "STATION_ENABLED", False)
    monkeypatch.setattr(config, "REAR_SOURCE", "none")
    assert set(compose("base.launch.py", real="false")["exes"]) == SIM_EXES | BASE_EXES
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.VEHICLE))
    c = compose("base.launch.py", real="true")
    assert set(c["exes"]) == HW_EXES | BASE_EXES | {"fake_panel_node"}
    assert "rear_scanner.launch.py" not in c["includes"]


def test_on_sim_adds_the_fake_trolley(monkeypatch):
    from agv_core import config
    monkeypatch.setattr(config, "STATION_ENABLED", True)
    c = compose("base.launch.py", real="false")
    assert set(c["exes"]) == SIM_EXES | BASE_EXES | {"fake_trolley_node", "station_bridge_node"}


def test_the_fake_trolley_is_never_launched_on_a_vehicle(monkeypatch):
    from agv_core import config
    monkeypatch.setattr(config, "STATION_ENABLED", True)
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.VEHICLE))
    c = compose("base.launch.py", real="true")
    assert "fake_trolley_node" not in c["exes"]
    assert set(c["exes"]) == HW_EXES | BASE_EXES | {"fake_panel_node", "station_bridge_node"}


def test_the_rear_source_follows_its_own_setting_not_the_switch(monkeypatch):
    from agv_core import config
    monkeypatch.setattr(config, "STATION_ENABLED", False)
    monkeypatch.setattr(config, "REAR_SOURCE", "scanner")
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.VEHICLE))
    c = compose("base.launch.py", real="true")
    assert "trolley_node" in c["exes"] and "rear_scanner.launch.py" in c["includes"]
    assert "station_bridge_node" not in c["exes"]
    assert c["exes"].count("robot_state_publisher") == 1


def test_the_rear_scanner_stays_off_the_front_topics():
    ld = get_launch_description_from_any_launch_file(os.path.join(LAUNCH, "rear_scanner.launch.py"))
    nodes = [e for e in ld.entities if isinstance(e, Node)]
    assert len(nodes) == 1
    with open(os.path.join(os.path.dirname(LAUNCH.rstrip("/")), "config", "nanoscan3_rear.yaml")) as fh:
        text = fh.read()
    assert "sick_safetyscanners2_rear_node" in text and "rear_laser_frame" in text
    assert "host_udp_port: 6060" not in text


def test_wrappers_compose_base_web_and_exactly_one_layer(tmp_path):
    from amr_mission.fixtures import write_world_as_bundle  # noqa: PLC0415

    write_world_as_bundle(str(tmp_path))
    m = compose("mapping.launch.py", sim="true", maps_dir=str(tmp_path))
    n = compose("nav.launch.py", sim="true", maps_dir=str(tmp_path), map_id="sim_factory")
    for c in (m, n):
        assert c["includes"].count("base.launch.py") == 1
        assert c["exes"].count("robot_state_publisher") == 1
        assert c["exes"].count("web_node") == 1
    assert set(m["exes"]) & MAPPING_EXES == MAPPING_EXES and not set(m["exes"]) & NAV_EXES
    assert set(n["exes"]) & NAV_EXES == NAV_EXES and not set(n["exes"]) & MAPPING_EXES


def test_hardware_wrapper_refuses_sim_domain():
    with pytest.raises(RuntimeError, match="vehicle"):
        compose("drivers.launch.py")


def test_q20_custom_footprint_reaches_the_costmap_node_through_a_params_file(tmp_path, monkeypatch):
    """An inline {"local_costmap.local_costmap.footprint": ...} dict would have set a parameter of
    that literal name on controller_server; the costmap node only sees a node-scoped file."""
    import yaml  # noqa: PLC0415
    from amr_mission.fixtures import write_world_as_bundle  # noqa: PLC0415

    write_world_as_bundle(str(tmp_path))
    fp = tmp_path / "fp.yaml"
    fp.write_text(
        "polygon:\n  - [-0.2, -0.1]\n  - [0.7, -0.1]\n  - [0.7, 0.1]\n  - [-0.2, 0.1]\nmargin_m: 0.05\n"
    )
    monkeypatch.setenv("AMR_STATE_DIR", str(tmp_path / "state"))
    c = compose(
        "navigation_layer.launch.py", maps_dir=str(tmp_path), map_id="sim_factory", footprint_yaml=str(fp)
    )
    from launch_ros.parameter_descriptions import ParameterFile  # noqa: PLC0415

    params = c["params"]["controller_server"]
    # no inline dict: nothing can land on the wrong node
    assert all(isinstance(p, ParameterFile) for p in params)
    files = ["".join(t.text for t in p._ParameterFile__param_file) for p in params]
    scoped = [f for f in files if "costmap_footprint" in f]
    assert len(scoped) == 1
    doc = yaml.safe_load(open(scoped[0]))
    assert doc["local_costmap"]["local_costmap"]["ros__parameters"]["footprint"] == (
        "[[-0.200, -0.100], [0.700, -0.100], [0.700, 0.100], [-0.200, 0.100]]"
    )


def _param_dict(p: dict) -> dict:
    """launch_ros (Humble) normalises a parameters dict: keys and values become tuples of
    substitutions, strings YAML-dumped. Perform and load them back, as launch_ros does."""
    import yaml  # noqa: PLC0415

    ctx = LaunchContext()

    def val(v):
        if isinstance(v, (tuple, list)) and v and all(hasattr(i, "perform") for i in v):
            return yaml.safe_load(_text(v, ctx))
        return v

    return {_text(k, ctx): val(v) for k, v in p.items()}


def _bundle_with_dynamic(tmp_path, big=False):
    from amr_mission.fixtures import write_world_as_bundle  # noqa: PLC0415

    from amr_mission import map_bundle as mb  # noqa: PLC0415

    write_world_as_bundle(str(tmp_path))
    # a mark over the aisle and the rack faces at y 2..2.5 (sim world), or over everything
    rect = (
        [[-50.0, -50.0], [50.0, -50.0], [50.0, 50.0], [-50.0, 50.0]]
        if big
        else [[4.0, -1.0], [9.0, -1.0], [9.0, 2.7], [4.0, 2.7]]
    )
    path, rev, _ = mb.derive_edit(str(tmp_path), "sim_factory", 1, [{"op": "dynamic", "polygon": rect}])
    return path, rev


def test_dynamic_mask_reaches_the_monitor_and_amcl_is_plain_by_default(tmp_path, monkeypatch):
    path, rev = _bundle_with_dynamic(tmp_path)
    monkeypatch.setenv("AMR_STATE_DIR", str(tmp_path / "state"))
    c = compose("navigation_layer.launch.py", maps_dir=str(tmp_path), map_id="sim_factory", revision=rev)
    assert set(c["exes"]) == NAV_EXES and c["exes"].count("map_server") == 1
    mon = [_param_dict(p) for p in c["params"]["localization_monitor_node"] if isinstance(p, dict)]
    assert mon[0]["dynamic_yaml"] == os.path.join(path, "dynamic.yaml")
    assert not (tmp_path / "state" / "loc_map_gen0.yaml").exists()


def test_the_line_layer_gives_the_monitor_its_maps_dynamic_areas(tmp_path, monkeypatch):
    from agv_core import paths  # noqa: PLC0415

    from amr_line import tape_graph_store as store  # noqa: PLC0415

    path, rev = _bundle_with_dynamic(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv(paths.MAPS_ENV, str(tmp_path))
    monkeypatch.setenv(paths.STATE_ENV, str(state))

    def monitor_mask(revision):
        store.write_active(str(state), "sim_factory", revision)
        c = compose("line_layer.launch.py", generation=3, real="true")
        return [_param_dict(p) for p in c["params"]["localization_monitor_node"] if isinstance(p, dict)][0][
            "dynamic_yaml"
        ]

    assert monitor_mask(rev) == os.path.join(path, "dynamic.yaml")
    assert monitor_mask(1) == ""  # the parent has no mask


def test_blank_dynamic_serves_amcl_a_derived_map_on_map_loc(tmp_path, monkeypatch):
    import numpy as np  # noqa: PLC0415

    from amr_maps import grid as gridio  # noqa: PLC0415

    path, rev = _bundle_with_dynamic(tmp_path)
    monkeypatch.setenv("AMR_STATE_DIR", str(tmp_path / "state"))
    c = compose(
        "navigation_layer.launch.py",
        maps_dir=str(tmp_path),
        map_id="sim_factory",
        revision=rev,
        blank_dynamic="true",
    )
    # map_server, map_server_loc, amcl, both managers (WP-H4), monitor, controller, behavior, executor
    assert c["exes"].count("map_server") == 2 and c["handlers"] == 9
    loc = gridio.read(str(tmp_path / "state" / "loc_map_gen0.yaml"))
    ref = gridio.read(os.path.join(path, "map.yaml"))
    dyn = gridio.read(os.path.join(path, "dynamic.yaml")).data >= 65
    assert (ref.data[dyn] >= 65).any()  # the fixture's rack/wall cells inside the mark...
    assert (loc.data[dyn] == -1).all()  # ...are unknown for AMCL
    assert np.array_equal(loc.data[~dyn], ref.data[~dyn])  # and nothing else changed


def test_blank_dynamic_refuses_a_map_with_nothing_fixed_left(tmp_path, monkeypatch):
    _, rev = _bundle_with_dynamic(tmp_path, big=True)
    monkeypatch.setenv("AMR_STATE_DIR", str(tmp_path / "state"))
    with pytest.raises(RuntimeError, match="nothing fixed to localise against"):
        compose(
            "navigation_layer.launch.py",
            maps_dir=str(tmp_path),
            map_id="sim_factory",
            revision=rev,
            blank_dynamic="true",
        )


def test_the_follower_and_executor_read_the_protective_field_index_of_the_yaml(tmp_path):
    """D165: one protective index (scanner_fields.yaml) for the mux, the follower and the
    executor. A wrong one makes them explain a stop from a warning path, never stops."""
    import math

    import yaml
    from amr_mission.fixtures import write_world_as_bundle

    from amr_bringup import scanner_fields
    from amr_maps import raycast

    doc = scanner_fields.load()
    assert scanner_fields.protective_index(doc) == scanner_fields.mux_params(doc)["protective_index"] == 0
    level = scanner_fields.protective_active_level(doc)  # WP-E3: the polarity from the same yaml
    assert level is doc["fields"]["protective"]["active"]
    c = compose("line_layer.launch.py", generation=3, real="true")
    params = [_param_dict(p) for p in c["params"]["line_follow_node"] if isinstance(p, dict)]
    assert any(p.get("field_output_index") == 0 for p in params)
    assert any(p.get("field_active_level") is level for p in params)
    write_world_as_bundle(str(tmp_path))
    n = compose("navigation_layer.launch.py", maps_dir=str(tmp_path), map_id="sim_factory")
    params = [_param_dict(p) for p in n["params"]["route_executor_node"] if isinstance(p, dict)]
    assert any(p.get("field_output_index") == 0 for p in params)
    assert any(p.get("field_active_level") is level for p in params)
    # the synthetic scan's field of view is the mounted scanner's
    cfg = yaml.safe_load(open(os.path.join(os.path.dirname(LAUNCH), "config", "nanoscan3.yaml")))
    ros = next(v["ros__parameters"] for v in cfg.values() if isinstance(v, dict) and "ros__parameters" in v)
    assert math.isclose(raycast.MOUNTED_FOV, ros["angle_end"] - ros["angle_start"], abs_tol=1e-3)


def test_foxglove_is_retired():
    """Unified plan WP-0A (owner, 2026-10-25): no launch argument, supervisor group,
    deploy variable or package dependency names Foxglove any more. Manuals may, and so
    does validate.sh, which warns about a leftover AMR_FOXGLOVE line."""
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    roots = [os.path.join(repo, d) for d in ("amr_ws/src", "amr_ws/deploy", "agv_core")]
    hits = []
    for root in roots:
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", "build", "install", "log")]
            for f in files:
                p = os.path.join(d, f)
                skip = p == os.path.abspath(__file__) or f == "validate.sh"
                if skip or not f.endswith((".py", ".xml", ".sh", ".env", ".yaml")):
                    continue
                with open(p, encoding="utf-8", errors="replace") as fh:
                    if "foxglove" in fh.read().lower():
                        hits.append(os.path.relpath(p, repo))
    assert hits == []
    for name in ("mapping", "nav", "sim", "drivers", "lidar"):
        src = open(os.path.join(LAUNCH, f"{name}.launch.py"), encoding="utf-8").read()
        assert "foxglove" not in src.lower(), name


def test_nav2_lifecycle_managers_do_not_rebond_a_dead_node():
    """WP-0D: a dead Nav2 node ends the layer (REQUIRED), and the supervisor replaces the
    layer. A lifecycle manager quietly re-bonding a respawned node would hide that. The
    two files are the ones navigation_layer.launch.py hands its managers."""
    import yaml

    seen = {}
    for pkg, f in (("amr_localization", "amcl.yaml"), ("amr_navigation", "nav2_params.yaml")):
        doc = yaml.safe_load(open(os.path.join(get_package_share_directory(pkg), "config", f)))
        for name, body in doc.items():
            if name.startswith("lifecycle_manager"):
                seen[name] = body["ros__parameters"].get("attempt_respawn_reconnection")
    assert seen == {"lifecycle_manager_localization": False, "lifecycle_manager_navigation": False}


def _node_name(node) -> str:
    return _text(node._Node__node_name, LaunchContext())  # private in Humble, raw as given


def test_lifecycle_managers_run_without_a_bond_and_are_required(tmp_path):
    """WP-C15 (C#24): bond_timeout 0.0 on both managers (no heartbeats, no false bond miss under
    N97 load). With no bond, required() is what catches a dead node: every localization and
    navigation node, the two managers included, ends the layer when it exits. A double, not an
    int: the manager's parameter type check would refuse an integer 0."""
    import yaml
    from amr_mission.fixtures import write_world_as_bundle

    for pkg, f in (("amr_localization", "amcl.yaml"), ("amr_navigation", "nav2_params.yaml")):
        doc = yaml.safe_load(open(os.path.join(get_package_share_directory(pkg), "config", f)))
        for name, body in doc.items():
            if name.startswith("lifecycle_manager"):
                bt = body["ros__parameters"]["bond_timeout"]
                assert isinstance(bt, float) and bt == 0.0, (f, name, bt)
    write_world_as_bundle(str(tmp_path))
    c = compose("navigation_layer.launch.py", maps_dir=str(tmp_path), map_id="sim_factory")
    watched = {id(n) for n in c["watched"]}
    names = sorted(_node_name(n) for _, n in c["nodes"] if id(n) in watched)
    assert names == sorted([
        "map_server", "amcl", "lifecycle_manager_localization", "localization_monitor",
        "controller_server", "behavior_server", "lifecycle_manager_navigation", "route_executor",
    ])


def test_both_layers_build_the_localization_group_once(tmp_path, monkeypatch):
    """L D53: navigation_layer and the LINE layer's tape localization both build map_server,
    AMCL, the manager and the monitor through tape_loc.group, so they cannot drift apart. Both
    pass the revision's dynamic areas to the monitor (dynamic_yaml), and the group's nodes are
    required in both."""
    from agv_core import paths  # noqa: PLC0415

    from amr_bringup import tape_loc  # noqa: PLC0415
    from amr_line import tape_graph_store as store  # noqa: PLC0415

    path, rev = _bundle_with_dynamic(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv(paths.MAPS_ENV, str(tmp_path))
    monkeypatch.setenv(paths.STATE_ENV, str(state))
    calls = []
    real_group = tape_loc.group

    def spy(*a, **kw):
        calls.append(kw)
        return real_group(*a, **kw)

    monkeypatch.setattr(tape_loc, "group", spy)
    store.write_active(str(state), "sim_factory", rev)
    line = compose("line_layer.launch.py", generation=3, real="true")
    nav = compose("navigation_layer.launch.py", maps_dir=str(tmp_path), map_id="sim_factory", revision=rev,
                  autostart="false")
    assert len(calls) == 2
    want = os.path.join(path, "dynamic.yaml")
    assert [kw.get("dynamic_yaml") for kw in calls] == [want, want]
    assert calls[1]["autostart"] is False and calls[1]["map_loc_yaml"] is None
    group = {"map_server", "amcl", "lifecycle_manager", "localization_monitor_node"}
    for c in (line, nav):
        watched = {id(n) for n in c["watched"]}
        got = {exe for exe, n in c["nodes"] if exe in group and id(n) in watched}
        assert got == group
        assert [exe for exe, _ in c["nodes"] if exe == "amcl"] == ["amcl"]
    lm = next(n for _, n in nav["nodes"] if _node_name(n) == "lifecycle_manager_localization")
    assert {"autostart": False} in [_param_dict(p) for p in lm._Node__parameters if isinstance(p, dict)]


def test_the_executor_assumes_the_field_clear_only_in_sim(tmp_path):
    """WP-A8: a vehicle navigation layer reads the scanner; only real:=false assumes clear."""
    from amr_mission.fixtures import write_world_as_bundle

    write_world_as_bundle(str(tmp_path))
    for real, want in (("true", "scanner"), ("false", "assume_clear")):
        c = compose("navigation_layer.launch.py", maps_dir=str(tmp_path), map_id="sim_factory", real=real)
        params = [_param_dict(p) for p in c["params"]["route_executor_node"] if isinstance(p, dict)]
        assert any(p.get("field_source") == want for p in params), (real, params)
    d = compose("navigation_layer.launch.py", maps_dir=str(tmp_path), map_id="sim_factory")
    params = [_param_dict(p) for p in d["params"]["route_executor_node"] if isinstance(p, dict)]
    assert any(p.get("field_source") == "scanner" for p in params), "the default is the vehicle"


# ---- WP-H4 (H-P1-5): every node is required or respawns; WP-P4 quiet logs; RFID off ------

# Nodes that are neither required() nor respawning, and why that is right.
NOT_SUPERVISED = {
    "fake_panel_node": "bench/sim stand-in (panel:=fake)",
    "fake_imu_node": "sim only",
    "fake_trolley_node": "sim only",
    "scan_synth_node": "sim only",
    "fake_output_paths_node": "sim only (WP-T2, AMR_SIM_FIELDS=1)",
}
# Respawning and optional (unified plan WP-H4 delta 2026-11-16): never BASE_EXITED. ROS respawn has
# no give-up limit in Humble, so a crash loop (wrong MQTT credentials: every 5 s) shows only in
# the role log until WP-H1's health rows report it.
RESPAWNING_OPTIONAL = {
    "station_bridge_node", "sick_safetyscanners2_node", "trolley_node", "rfid_node", "imu_bias_node",
    "survey_move_node", "event_recorder_node",
}


def _respawns(node) -> bool:
    return node._ExecuteLocal__respawn is True and (node._ExecuteLocal__respawn_delay or 0) > 0


def _all_bases(monkeypatch):
    from agv_core import config
    monkeypatch.setattr(config, "STATION_ENABLED", True)
    monkeypatch.setattr(config, "REAR_SOURCE", "scanner")
    monkeypatch.setattr(config, "RFID_ENABLED", True)
    sim = compose("base.launch.py", real="false", supervised="true")
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.VEHICLE))
    real = compose("base.launch.py", real="true", supervised="true")
    return sim, real


def test_every_node_is_required_or_respawns(monkeypatch):
    sim, real = _all_bases(monkeypatch)
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.SIM))
    layers = [compose("line_layer.launch.py", generation=1, real="true"), compose("mapping_layer.launch.py")]
    for c in [sim, real, *layers]:
        watched = {id(n) for n in c.get("watched", [])}
        for exe, node in c["nodes"]:
            if id(node) in watched:
                assert exe not in RESPAWNING_OPTIONAL, f"{exe} is required and on the optional list"
                continue
            if _respawns(node):
                assert exe in RESPAWNING_OPTIONAL, f"{exe} respawns but is not on the allow-list"
                continue
            assert exe in NOT_SUPERVISED, f"{exe} is neither required() nor respawning"


def test_the_station_bridge_rear_scanner_and_trolley_respawn_and_are_optional(monkeypatch):
    _, real = _all_bases(monkeypatch)
    watched = {id(n) for n in real.get("watched", [])}
    seen = {exe for exe, n in real["nodes"] if _respawns(n) and id(n) not in watched}
    assert {"station_bridge_node", "sick_safetyscanners2_node", "trolley_node"} <= seen
    assert [exe for exe, _ in real["nodes"]].count("sick_safetyscanners2_node") == 2  # front and rear


def test_commissioning_node_is_required_when_supervised(monkeypatch):
    _, real = _all_bases(monkeypatch)
    watched = {id(n) for n in real.get("watched", [])}
    node = next(n for exe, n in real["nodes"] if exe == "commissioning_node")
    assert id(node) in watched


def test_rfid_node_starts_only_when_the_profile_enables_it(monkeypatch):
    from agv_core import config
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.VEHICLE))
    monkeypatch.setattr(config, "RFID_ENABLED", False)
    assert "rfid_node" not in compose("base.launch.py", real="true")["exes"]
    monkeypatch.setattr(config, "RFID_ENABLED", True)
    assert "rfid_node" in compose("base.launch.py", real="true")["exes"]


def test_both_profiles_leave_rfid_off():
    import json  # noqa: PLC0415

    root = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "profiles")
    for name in ("agv-01.json", "agv-02.json"):
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            assert json.load(fh)["rfid"]["enabled"] is False, name


def _ros_args(node) -> list:
    raw = list(getattr(node, "_Node__ros_arguments", None) or [])
    raw += list(getattr(node, "_Node__arguments", None) or [])
    ctx = LaunchContext()
    return [_text(a, ctx) for a in raw]


def test_nodes_whose_output_reaches_the_role_log_skip_the_ros_log_files(monkeypatch):
    """S-ros-log-bounding: --disable-external-lib-logs on base, line, mapping and scanner nodes."""
    from amr_bringup.launch_helpers import QUIET_FLAG  # noqa: PLC0415

    sim, real = _all_bases(monkeypatch)
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.SIM))
    layers = [compose("line_layer.launch.py", generation=1, real="true"), compose("mapping_layer.launch.py")]
    for c in [sim, real, *layers]:
        for exe, node in c["nodes"]:
            if exe == "robot_state_publisher":
                continue  # amr_description's launch: not changed (WP-P4 kept to amr_bringup)
            assert QUIET_FLAG in _ros_args(node), exe


# ---- WP-H3 event recorder, WP-P6 black box, WP-T2 sim fields ----------------------------------


def test_the_event_recorder_runs_in_every_base_and_respawns(monkeypatch):
    sim, real = _all_bases(monkeypatch)
    for c in (sim, real):
        rec = [n for exe, n in c["nodes"] if exe == "event_recorder_node"]
        assert len(rec) == 1 and _respawns(rec[0])
        assert id(rec[0]) not in {id(n) for n in c.get("watched", [])}  # optional: never BASE_EXITED


def test_the_black_box_is_off_by_default_and_never_required(monkeypatch):
    """WP-P6: default off until the owner's pidstat check; on, a snapshot-mode recorder named
    amr_blackbox and its trigger, both respawning plain processes (no exit handler)."""
    from amr_bringup import blackbox

    monkeypatch.delenv(blackbox.ENV, raising=False)
    assert compose("base.launch.py", real="false").get("procs", []) == []
    c = compose("base.launch.py", real="false", blackbox="true")
    procs = c["procs"]
    assert len(procs) == 2 and all(_respawns(e) for e, _ in procs)
    assert c.get("handlers", 0) == compose("base.launch.py", real="false").get("handlers", 0)
    rec = next(cmd for _, cmd in procs if cmd[:2] == ["sh", "-c"])
    for want in ("--snapshot-mode", "--node-name amr_blackbox", "-s mcap", blackbox.DEVICE_HEALTH_TOPIC,
                 "/amr/line/order_state", "/amr/rear/trolley", "/amr/events"):
        assert want in rec[2], want
    for fast in (" /scan ", " /amr/line_track ", " /cmd_wheel_vel ", " /map "):
        assert fast not in rec[2] + " ", fast
    trig = next(cmd for _, cmd in procs if "amr_bringup.blackbox_node" in cmd)
    assert "-m" in trig
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.VEHICLE))
    monkeypatch.setenv(blackbox.ENV, "true")
    assert len(compose("base.launch.py", real="true").get("procs", [])) == 2  # the env turns it on


def test_fake_output_paths_is_opt_in_sim_only_and_never_on_a_vehicle(monkeypatch):
    """WP-T2 (S-fake-output-paths-from-field-geometry): only the sim branch with AMR_SIM_FIELDS=1;
    then the mux and the follower read /output_paths instead of assuming the field clear. A vehicle
    launch never carries it, whatever the environment says."""
    from amr_bringup.launch_helpers import SIM_FIELDS_ENV

    monkeypatch.delenv(SIM_FIELDS_ENV, raising=False)
    assert "fake_output_paths_node" not in compose("base.launch.py", real="false")["exes"]
    monkeypatch.setenv(SIM_FIELDS_ENV, "1")
    sim = compose("base.launch.py", real="false")
    assert sim["exes"].count("fake_output_paths_node") == 1
    mux = [_param_dict(p) for p in sim["params"]["cmd_mux_kinematics_node"] if isinstance(p, dict)]
    assert any(p.get("field_source") == "scanner" for p in mux)
    line = compose("line_layer.launch.py", generation=3, real="false")
    params = [_param_dict(p) for p in line["params"]["line_follow_node"] if isinstance(p, dict)]
    assert any(p.get("field_source") == "scanner" for p in params)
    monkeypatch.setenv("ROS_DOMAIN_ID", str(domains.VEHICLE))
    real = compose("base.launch.py", real="true")
    assert not {"fake_output_paths_node", "fake_trolley_node", "fake_base_node", "fake_imu_node"} & set(
        real["exes"]
    )


def test_both_scanner_drivers_take_their_addresses_from_the_profile(monkeypatch):
    """WP-P10: lidar.* feeds the front driver, rear.* the rear one (agv_core.scanner_config), passed
    after the yaml so the profile wins for sensor_ip, host_ip and host_udp_port."""
    from agv_core import config, scanner_config

    _, real = _all_bases(monkeypatch)
    want = {
        "sick_safetyscanners2_node": scanner_config.driver_params(config, scanner_config.FRONT),
        "sick_safetyscanners2_rear_node": scanner_config.driver_params(config, scanner_config.REAR),
    }
    seen = {}
    for exe, n in real["nodes"]:
        if exe != "sick_safetyscanners2_node":
            continue
        dicts = [_param_dict(p) for p in (n._Node__parameters or []) if isinstance(p, dict)]
        seen[_node_name(n)] = {k: v for d in dicts for k, v in d.items()
                               if k in ("sensor_ip", "host_ip", "host_udp_port")}
    assert seen == want
    assert want["sick_safetyscanners2_node"]["host_udp_port"] != want["sick_safetyscanners2_rear_node"][
        "host_udp_port"
    ]

