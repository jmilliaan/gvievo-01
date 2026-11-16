"""WP-C9 (cpu-load C#17, 2026-11-16): the mux thins only an idle zero to 10 Hz.

gating.wheel_publish_due is pure with an injected clock. Anything that can move the
vehicle, or changes what the drive owner last heard, is published on its tick; only a
repeated zero with source NONE in the same generation waits for the 0.1 s period, which
is half the drive owner's own command timeout (a lost idle zero still reads as zero).
"""

import random

import pytest
from agv_core import config

from amr_base import gating
from amr_base.gating import FOLLOW, IDLE_ZERO_PERIOD_S, LINE, NONE, PENDANT, WheelOut, wheel_publish_due

DT = 0.02  # the mux tick (rate_hz 50)
PERIOD = IDLE_ZERO_PERIOD_S - DT / 2  # what the node passes


def idle(t, gen=3):
    return WheelOut(t, gen, NONE, 0.0, 0.0)


def test_the_first_tick_publishes():
    assert wheel_publish_due(0.0, None, 0, NONE, 0.0, 0.0, PERIOD)


def test_any_nonzero_is_published_on_its_tick():
    last = WheelOut(10.0, 3, FOLLOW, 1.0, 1.0)
    for src in (FOLLOW, LINE, PENDANT, NONE):  # NONE + nonzero cannot happen; publish anyway
        for wl, wr in ((1.0, 1.0), (0.0, 1e-9), (-0.3, 0.0), (float("nan"), 0.0)):
            assert wheel_publish_due(10.0, last, 3, src, wl, wr, PERIOD)
    # a nonzero right after an idle zero, inside the idle period: published at once
    assert wheel_publish_due(10.001, idle(10.0), 3, FOLLOW, 0.5, 0.5, PERIOD)


def test_the_first_zero_after_a_nonzero_is_published():
    assert wheel_publish_due(10.02, WheelOut(10.0, 3, NONE, 0.4, -0.4), 3, NONE, 0.0, 0.0, PERIOD)
    assert wheel_publish_due(10.02, WheelOut(10.0, 3, FOLLOW, 0.4, 0.4), 3, NONE, 0.0, 0.0, PERIOD)


def test_a_source_change_to_none_is_published():
    # a held stop under FOLLOW (zero output), then the source drops to NONE
    assert wheel_publish_due(10.02, WheelOut(10.0, 3, FOLLOW, 0.0, 0.0), 3, NONE, 0.0, 0.0, PERIOD)


def test_a_generation_change_is_published():
    assert wheel_publish_due(10.02, idle(10.0, gen=3), 4, NONE, 0.0, 0.0, PERIOD)
    assert not wheel_publish_due(10.02, idle(10.0, gen=3), 3, NONE, 0.0, 0.0, PERIOD)


def test_a_zero_under_an_authority_is_published_every_tick():
    # a held stop (LINE at a mark, FOLLOW timed out, a factor-0 warning) is not thinned
    for src in (FOLLOW, LINE, PENDANT):
        last = WheelOut(10.0, 3, src, 0.0, 0.0)
        assert wheel_publish_due(10.02, last, 3, src, 0.0, 0.0, PERIOD)
        assert wheel_publish_due(10.0, last, 3, src, 0.0, 0.0, PERIOD)


def test_minus_zero_is_an_exact_zero():
    assert not wheel_publish_due(10.02, idle(10.0), 3, NONE, -0.0, 0.0, PERIOD)


def test_a_clock_that_reads_backwards_publishes():
    assert wheel_publish_due(9.9, idle(10.0), 3, NONE, 0.0, 0.0, PERIOD)


def _run(ticks, jitter=0.0, seed=1):
    """Drive the rule tick by tick: (time, source, wl) -> the times published."""
    rnd = random.Random(seed)
    last, sent = None, []
    for k, (src, wl) in enumerate(ticks):
        t = k * DT + (rnd.uniform(-jitter, jitter) if k else 0.0)
        if wheel_publish_due(t, last, 3, src, wl, wl, PERIOD):
            last = WheelOut(t, 3, src, wl, wl)
            sent.append(t)
    return sent


def test_a_repeated_idle_zero_goes_out_at_10_hz():
    sent = _run([(NONE, 0.0)] * 50)  # 1 s idle at 50 Hz
    assert len(sent) == 10
    gaps = [b - a for a, b in zip(sent, sent[1:], strict=False)]
    assert all(g == pytest.approx(IDLE_ZERO_PERIOD_S) for g in gaps)


def test_tick_jitter_cannot_stretch_the_idle_gap_past_one_tick():
    sent = _run([(NONE, 0.0)] * 500, jitter=0.004)
    gaps = [b - a for a, b in zip(sent, sent[1:], strict=False)]
    assert max(gaps) <= IDLE_ZERO_PERIOD_S + 2 * 0.004 + 1e-9
    assert max(gaps) < gating.DEFAULT.cmd_timeout_s


def test_driving_between_idle_spells_is_published_every_tick():
    ticks = [(NONE, 0.0)] * 10 + [(FOLLOW, 0.5)] * 5 + [(FOLLOW, 0.0)] * 3 + [(NONE, 0.0)] * 10
    sent = _run(ticks)
    t = [k * DT for k in range(len(ticks))]
    assert t[0] in sent and t[5] in sent and t[6] not in sent  # idle: 0, 0.1 s
    assert all(t[k] in sent for k in range(10, 18))  # every FOLLOW tick, nonzero and held zero
    assert t[18] in sent  # the first NONE zero after FOLLOW
    assert t[19] not in sent and t[23] in sent  # then 10 Hz again


def test_the_margin_against_the_drive_owner_timeout():
    # drive_node's watchdog is canopen.target_rpm(cmd, now, cmd_timeout_s, ...) with
    # cmd_timeout_s = config.FRESH_CMD_S (profile freshness.cmd_s, hard ceiling 0.2 s)
    assert 2 * IDLE_ZERO_PERIOD_S <= config.FRESH_CMD_S
    assert 2 * IDLE_ZERO_PERIOD_S <= gating.DEFAULT.cmd_timeout_s


def test_the_mux_tick_publishes_through_the_rule():
    # Node-level: needs rclpy and the message packages (the vehicle), skipped on the dev box.
    pytest.importorskip("rclpy")
    pytest.importorskip("builtin_interfaces")
    from types import SimpleNamespace

    from builtin_interfaces.msg import Time

    from amr_base import cmd_mux_kinematics_node as mux
    from amr_base.diff_drive import profile_geometry

    class _Logger:
        def info(self, *_a, **_k):
            pass

        warn = error = warning = info

    n = mux.CmdMuxKinematics.__new__(mux.CmdMuxKinematics)
    n.geom = profile_geometry()
    n.w_max = 100.0
    n.a_max, n.alpha_max, n.d_max, n.delta_max = 0.15, 0.4, 0.5, 1.0
    n.manual_a_max, n.manual_alpha_max, n.manual_jerk, n.manual_jerk_w = 0.3, 0.4, 1.0, 2.0
    n.dt = DT
    n.gp = gating.Params()
    n._teleop = n._follow = n._rotate = n._permit = n._panel = n._lease = n._drives = None
    n._manual = gating.ManualIntake()
    n._commissioning = None
    n._v = n._wz = n._wl = n._wr = n._a = n._alpha = 0.0
    n._source, n._reason, n._applied_gen = "none", "", 3
    n._inhibited, n._event_seq = False, 0
    n._pub_event = SimpleNamespace(publish=lambda _m: None)
    n._last = gating.Selection(gating.NONE, 0.0, 0.0, "", 0, False)
    clock = [10.0]
    n._now = lambda: clock[0]
    n.get_logger = lambda: _Logger()
    n.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: Time()))
    sent = []
    n._pub = SimpleNamespace(publish=sent.append)
    n.survey_w_max, n._surveying = 0.27, False

    keep = mux.gating.select
    try:
        mux.gating.select = lambda *_a, **_k: gating.Selection(gating.NONE, 0.0, 0.0, "no source", 3)
        for _ in range(50):
            n._tick()
            clock[0] += DT
        assert len(sent) == 10  # 1 s idle
        n._applied_gen = 4  # a new layer
        n._tick()
        assert len(sent) == 11 and sent[-1].generation == 4
        clock[0] += DT
        mux.gating.select = lambda *_a, **_k: gating.Selection(gating.LINE, 0.0, 0.0, "line", 4)
        for _ in range(5):  # a held stop under LINE: every tick
            n._tick()
            clock[0] += DT
        assert len(sent) == 16
    finally:
        mux.gating.select = keep
