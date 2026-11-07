"""Station call plan P3: the node's wiring. Real rclpy, no graph beyond the node."""

import time
import types

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("amr_interfaces.msg")
from agv_core import config  # noqa: E402
from std_srvs.srv import Trigger  # noqa: E402

from amr_line import job as lj  # noqa: E402
from amr_line import line_follow_node as lfn  # noqa: E402


@pytest.fixture()
def node(request, monkeypatch, tmp_path):
    monkeypatch.setenv("ROS_DOMAIN_ID", "87")
    on = request.param
    monkeypatch.setattr(config, "STATION_ENABLED", on)
    rclpy.init()
    n = lfn.LineFollowNode.__new__(lfn.LineFollowNode)
    lfn.LineFollowNode.__init__(n)
    yield n
    n.destroy_node()
    rclpy.shutdown()


def _names(n):
    return {name for name, _t in n.get_service_names_and_types_by_node("line_follow_node", "/")}


@pytest.mark.parametrize("node", [False], indirect=True)
def test_off_the_node_has_no_order_service_or_topic(node):
    assert node.job.calling is False and node._order_pub is None
    time.sleep(0.2)
    assert "/amr/line/order" not in _names(node) and "/amr/line/trip" in _names(node)
    topics = {t for t, _ty in node.get_publisher_names_and_types_by_node("line_follow_node", "/")}
    assert "/amr/line/order_state" not in topics
    subs = {t for t, _ty in node.get_subscriber_names_and_types_by_node("line_follow_node", "/")}
    assert "/amr/rear/trolley" not in subs


@pytest.mark.parametrize("node", [True], indirect=True)
def test_on_a_stale_trolley_message_is_unknown(node):
    from amr_interfaces.msg import TrolleyState

    assert node._rear(time.monotonic()) == ("unknown", None)
    m = TrolleyState(state=TrolleyState.ABSENT, rear_field=TrolleyState.FIELD_CLEAR)
    node._on_trolley(m)
    now = time.monotonic()
    assert node._rear(now) == ("absent", True)
    assert node._rear(now + node.field_fresh + 0.1) == ("unknown", None)
    node._on_trolley(TrolleyState(state=TrolleyState.PRESENT, rear_field=TrolleyState.FIELD_VIOLATED))
    assert node._rear(time.monotonic()) == ("present", False)
    node._on_trolley(TrolleyState(state=TrolleyState.ABSENT, rear_field=TrolleyState.FIELD_UNKNOWN))
    assert node._rear(time.monotonic()) == ("absent", None)


class FakeLoc:
    ready = True

    def snapshot(self):
        return {}

    def loc_state(self):
        return None

    def at_home(self, fresh_ready=False):
        self.fresh_ready = fresh_ready
        return True, "At home", (0.0, 0.0, 0.0)


def _panel(node, auto, valid=True):
    node._on_panel(types.SimpleNamespace(valid=valid, mode_auto=auto, start_edge=False, reset_edge=False))


@pytest.mark.parametrize("node", [True], indirect=True)
def test_at_home_needs_manual_with_calling_on(node):
    node.tapeloc = FakeLoc()
    res = node._srv_at_home(Trigger.Request(), Trigger.Response())
    assert not res.success and "MANUAL" in res.message, "no panel at all"
    _panel(node, auto=True)
    assert not node._srv_at_home(Trigger.Request(), Trigger.Response()).success
    _panel(node, auto=False, valid=False)
    assert not node._srv_at_home(Trigger.Request(), Trigger.Response()).success
    _panel(node, auto=False)
    assert node._srv_at_home(Trigger.Request(), Trigger.Response()).success
    assert node.tapeloc.fresh_ready is True


@pytest.mark.parametrize("node", [False], indirect=True)
def test_at_home_unchanged_with_calling_off(node):
    node.tapeloc = FakeLoc()
    _panel(node, auto=True)
    assert node._srv_at_home(Trigger.Request(), Trigger.Response()).success
    assert node.tapeloc.fresh_ready is False


@pytest.mark.parametrize("node", [True, False], indirect=True)
@pytest.mark.parametrize("state", [lj.ARMED, lj.RUNNING, lj.HOLD, lj.FAULT])
def test_at_home_is_refused_while_the_job_is_busy(node, state):
    node.tapeloc = FakeLoc()
    _panel(node, auto=False)
    node.job.state = state
    res = node._srv_at_home(Trigger.Request(), Trigger.Response())
    assert not res.success and "refused" in res.message
    assert not hasattr(node.tapeloc, "fresh_ready"), "the locator was left alone"
    assert not node._position.checking


@pytest.mark.parametrize("node", [True], indirect=True)
def test_at_home_is_refused_with_a_trip_or_moving_wheels(node):
    node.tapeloc = FakeLoc()
    _panel(node, auto=False)
    node.job.trip = object()
    assert "with a trip" in node._srv_at_home(Trigger.Request(), Trigger.Response()).message
    node.job.trip = None
    node._wheel_inputs = lambda now: ((1, 1), 100.0, False)
    assert "moving" in node._srv_at_home(Trigger.Request(), Trigger.Response()).message
    assert not hasattr(node.tapeloc, "fresh_ready")


@pytest.mark.parametrize("node", [True], indirect=True)
def test_at_home_arms_the_check_and_a_recovery_keeps_the_locator_and_baseline(node):
    node.tapeloc = FakeLoc()
    _panel(node, auto=False)
    assert node._srv_at_home(Trigger.Request(), Trigger.Response()).success
    assert node._position.checking
    node._position.press(0.0, None)
    # The node's seed path, as a recovery uses it, touches neither.
    node.tapeloc = types.SimpleNamespace()
    base = node.job._home_base = (1, 1)
    node._publish_seed((0.0, 0.0, 0.0))
    assert node.job._home_base == base and vars(node.tapeloc) == {}


@pytest.mark.parametrize("node", [True], indirect=True)
def test_a_pose_from_mapping_is_never_auto_confirmed(node):
    from amr_line import position_confirm as pc

    p = pc.PositionConfirm(pc.Params(at_home=True, recover=True, hold_s=1.0, timeout_s=20.0, max_offset_m=1.0,
                                     settle_s=3.0, retry_s=60.0, wheel_dia_m=0.18))
    f = pc.Facts(now=5.0, monitor_state=pc.CHECKING, monitor_t=5.0, can_confirm=True, job_idle=True,
                 tape_seen=True, parked_at_home=True, wheels_still=True)
    assert p.tick(f) == "" and not p.checking


@pytest.mark.parametrize("node", [True], indirect=True)
def test_clear_in_fault_replies_refused_with_calling_on(node):
    node.job.state = lj.FAULT
    res = node._srv_clear(Trigger.Request(), Trigger.Response())
    assert not res.success and res.message == "press Reset on the panel" and node.job.state == lj.FAULT


@pytest.mark.parametrize("node", [True], indirect=True)
def test_the_order_service_only_latches(node):
    from amr_interfaces.srv import LineTeach

    res = node._srv_order(LineTeach.Request(action="depart", arg="O1 MRU1"), LineTeach.Response())
    assert res.ok and res.message == "taken" and node.job.state == lj.IDLE
    res = node._srv_order(LineTeach.Request(action="go", arg=""), LineTeach.Response())
    assert not res.ok


@pytest.mark.parametrize("node", [True], indirect=True)
def test_order_state_publishes_with_the_jobs_fields(node):
    node._publish_order(force=True)
    assert node._order_published["not_ready"] == [] and node._order_published["driving"] is False
