"""Stateful property test of gating.select() (S-hypothesis-stateful-gating, unified plan WP-T1,
2026-11-16). Random interleavings of ticks, lease renewals and generation changes, selector flips,
pendant levels, manual/line/follow streams, permits and drive reports; after every step the
mux's invariants must hold. Derandomized and capped. Not counted in tests/run_all.py
EXPECTED_CHECKS. Skips where hypothesis is not installed (apt python3-hypothesis)."""

import math
from types import SimpleNamespace

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule  # noqa: E402

from amr_base import gating as g  # noqa: E402

P = g.Params(require_supervisor=True)
INSTANCE = "sup-1"
CLASSES = st.sampled_from([0, g.LEASE_MANUAL, g.LEASE_AUTONOMOUS, g.LEASE_LINE, g.LEASE_COMMISSIONING])
SPEED = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)


class Mux(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.now = 100.0
        self.gen = 1
        self.lease = None
        self.panel = None
        self.drives = None
        self.permit = None
        self.manual = None
        self.line = self.follow = self.rotate = self.teleop = None
        self.sel = None

    # -- the world -------------------------------------------------------------------
    @rule(dt=st.floats(min_value=0.0, max_value=0.4))
    def tick(self, dt):
        self.now += dt

    @rule(allowed=CLASSES)
    def renew_lease(self, allowed):
        self.lease = g.Lease(self.now, INSTANCE, self.gen, 0, allowed)

    @rule()
    def new_generation(self):
        self.gen += 1

    @rule(valid=st.booleans(), auto=st.booleans(), fwd=st.booleans(), left=st.booleans())
    def panel_image(self, valid, auto, fwd, left):
        self.panel = g.Panel(self.now, valid, auto, fwd=fwd, left=left)

    @rule(operational=st.booleans())
    def drive_report(self, operational):
        self.drives = g.Drives(self.now, operational)

    @rule(source=st.sampled_from([g.FOLLOW, g.ROTATE]), enabled=st.booleans(), old_gen=st.booleans())
    def permit_sample(self, source, enabled, old_gen):
        self.permit = g.Permit(self.now, source, enabled, INSTANCE, self.gen - int(old_gen))

    @rule(v=SPEED, w=SPEED, valid_for=st.floats(min_value=-0.1, max_value=0.5), old_gen=st.booleans())
    def manual_sample(self, v, w, valid_for, old_gen):
        self.manual = g.Manual(self.now, v, w, INSTANCE, self.gen - int(old_gen), "s", 0, valid_for)

    @rule(which=st.sampled_from(["line", "follow", "rotate", "teleop"]), v=SPEED, w=SPEED)
    def stream_sample(self, which, v, w):
        setattr(self, which, g.Stamped(self.now, v, w))

    @rule()
    def select(self):
        self.sel = g.select(self.now, self.teleop, self.follow, self.rotate, self.permit, self.panel, P,
                            lease=self.lease, manual=self.manual, drives=self.drives, line=self.line)
        # The world the selection was made from. The invariants judge a selection against it, not
        # against inputs that changed after it: the real mux selects again on its next tick
        # (agv-01 2026-11-17: a drive report after select() failed a valid selection).
        self.w = SimpleNamespace(now=self.now, lease=self.lease, panel=self.panel, drives=self.drives,
                                 permit=self.permit, manual=self.manual, line=self.line, follow=self.follow,
                                 rotate=self.rotate, teleop=self.teleop)

    # -- the invariants ----------------------------------------------------------------
    @invariant()
    def nothing_moves_without_fresh_authority(self):
        s = self.sel
        if s is None or (s.v == 0.0 and s.w == 0.0):
            return
        w = self.w
        assert w.lease is not None and 0.0 <= w.now - w.lease.t_recv <= P.lease_timeout_s
        assert w.drives is not None and w.drives.operational
        assert 0.0 <= w.now - w.drives.t_recv <= P.drives_timeout_s
        assert w.panel is not None and w.panel.valid
        assert 0.0 <= w.now - w.panel.t_recv <= P.panel_timeout_s
        assert s.generation == w.lease.generation

    @invariant()
    def a_moving_source_is_fresh_and_of_this_generation(self):
        s = self.sel
        if s is None or (s.v == 0.0 and s.w == 0.0):
            return
        w = self.w
        assert math.isfinite(s.v) and math.isfinite(s.w)
        if s.source == g.MANUAL:
            m = w.manual
            assert m.generation == w.lease.generation
            assert 0.0 <= w.now - m.t <= min(P.cmd_timeout_s, max(0.0, m.valid_for_s))
        elif s.source in (g.LINE, g.FOLLOW, g.ROTATE, g.TELEOP):
            streams = {g.LINE: w.line, g.FOLLOW: w.follow, g.ROTATE: w.rotate, g.TELEOP: w.teleop}
            cmd = streams[s.source]
            assert 0.0 <= w.now - cmd.t <= P.cmd_timeout_s
        if s.source in (g.FOLLOW, g.ROTATE):
            assert w.permit.enabled and w.permit.generation == w.lease.generation
            assert 0.0 <= w.now - w.permit.t_recv <= P.permit_timeout_s
        if s.source in (g.FOLLOW, g.ROTATE, g.LINE):
            assert w.panel.auto
        if s.source in (g.MANUAL, g.TELEOP, g.PENDANT):
            assert not w.panel.auto


Mux.TestCase.settings = settings(derandomize=True, max_examples=200, stateful_step_count=40, deadline=None)
TestMux = Mux.TestCase
