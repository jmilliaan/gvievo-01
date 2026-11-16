"""Emergency-suite plan Part B E4 on the mux node (SAFETY-LISTED: cmd_mux_kinematics_node.py).

While PanelState.emergency is not NORMAL the tick selects NONE (ESTOP) and the speed, the S-curve
acceleration and the per-wheel slew state are zero at once, not ramped. After NORMAL a pendant held
through the Reset keeps them at zero until it is released once; the open no_jerk question (a ramp
that keeps an acceleration after landing) is checked here for the mux: nothing survives the stop.
Needs rclpy (the node module imports it), like test_mux_manual_profile.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("rclpy")

from builtin_interfaces.msg import Time  # noqa: E402

from amr_base import cmd_mux_kinematics_node as mux  # noqa: E402
from amr_base import gating  # noqa: E402
from amr_base.diff_drive import profile_geometry  # noqa: E402


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, text, *_a, **_k):
        self.lines.append(text)

    warn = error = warning = info


def _node(t=[10.0]):  # noqa: B006 - one clock for the test
    n = mux.CmdMuxKinematics.__new__(mux.CmdMuxKinematics)
    n.geom = profile_geometry()
    n.w_max = 100.0
    n.a_max, n.alpha_max, n.d_max, n.delta_max = 0.15, 0.4, 0.5, 1.0
    n.manual_a_max, n.manual_alpha_max, n.manual_jerk, n.manual_jerk_w = 0.3, 0.4, 1.0, 2.0
    n.dt = 0.02
    n.gp = gating.Params()
    n._teleop = n._follow = n._rotate = n._permit = n._panel = n._lease = n._drives = None
    n._manual = gating.ManualIntake()
    n._commissioning = None
    n._v = n._wz = n._wl = n._wr = n._a = n._alpha = 0.0
    n._source, n._reason, n._applied_gen = "none", "", 0
    n._inhibited, n._event_seq = False, 0
    n._pub_event = SimpleNamespace(publish=lambda _m: None)
    n._last = gating.Selection(gating.NONE, 0.0, 0.0, "", 0, False)
    n._now = lambda: t[0]
    log = _Logger()
    n.get_logger = lambda: log
    n.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: Time()))
    n._pub = SimpleNamespace(publish=lambda _m: None)
    n.survey_w_max, n._surveying = 0.27, False
    return n


def _panel(n, emergency=0, fwd=True):
    n._panel = gating.Panel(n._now(), True, False, fwd=fwd, emergency=emergency)


def _ticks(n, k):
    for _ in range(k):
        _panel(n, n._panel.emergency, n._panel.fwd)  # a fresh image every tick
        n._tick()


def test_an_estop_zeroes_speed_and_ramp_state_at_once_and_a_held_pendant_stays_dead():
    n = _node()
    _panel(n)
    _ticks(n, 40)  # pendant FWD for 0.8 s: moving, the S-curve mid-ramp
    assert n._v > 0.0 and n._last.source == gating.PENDANT
    _panel(n, emergency=1)
    _ticks(n, 1)
    assert (n._v, n._wz, n._a, n._alpha, n._out) == (0.0, 0.0, 0.0, 0.0, (0.0, 0.0))
    assert (n._last.code, n._last.inhibited) == ("ESTOP", True)
    for emg in (2, 3, 0):  # released, Reset, NORMAL: the pendant still held throughout
        _panel(n, emergency=emg)
        _ticks(n, 25)
        assert (n._v, n._a, n._out) == (0.0, 0.0, (0.0, 0.0)), emg
    assert n._last.source == gating.NONE and "release the pendant" in n._last.reason
    _panel(n, fwd=False)
    _ticks(n, 2)  # let go once
    assert "manual motion allowed again" in " ".join(n.get_logger().lines)
    _panel(n)
    _ticks(n, 5)
    assert n._last.source == gating.PENDANT and n._v > 0.0, "a fresh press drives"


def test_the_ramp_restarts_from_zero_after_the_emergency():
    """No acceleration carried across the stop (the mux's side of the no_jerk question): the first
    tick after the release-and-press builds acceleration from zero at the jerk limit."""
    n = _node()
    _panel(n)
    _ticks(n, 20)
    _panel(n, emergency=1)
    _ticks(n, 1)
    _panel(n, fwd=False)
    _ticks(n, 2)
    _panel(n)
    _ticks(n, 1)
    assert n._a == pytest.approx(n.manual_jerk * n.dt)
    assert n._v == pytest.approx(n._a * n.dt)


def test_a_line_selection_is_zeroed_by_the_estop_too():
    n = _node()
    n.gp = gating.Params(require_supervisor=True)
    n._lease = gating.Lease(10.0, "i", 1, 1, gating.LEASE_LINE)
    n._drives = gating.Drives(10.0, True)
    n._line = gating.Stamped(10.0, 0.5, 0.0)
    n._panel = gating.Panel(10.0, True, True)
    n._tick()
    assert n._last.source == gating.LINE and n._v > 0.0
    n._panel = gating.Panel(10.0, True, True, emergency=1)
    n._tick()
    assert (n._last.code, n._v, n._wz, n._out) == ("ESTOP", 0.0, 0.0, (0.0, 0.0))


def test_on_panel_reads_the_emergency_and_defaults_to_normal():
    n = _node()
    msg = SimpleNamespace(valid=True, mode_auto=False, pendant_fwd=False, pendant_rvs=False,
                          pendant_left=False, pendant_right=False, emergency=3)
    n._on_panel(msg)
    assert n._panel.emergency == 3
    del msg.emergency  # a PanelState built before the field
    n._on_panel(msg)
    assert n._panel.emergency == 0
