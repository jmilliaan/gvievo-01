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
