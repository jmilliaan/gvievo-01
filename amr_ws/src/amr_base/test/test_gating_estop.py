"""Emergency-suite plan Part B E4 (2026-11-16): the mux's no-motion layers. SAFETY-LISTED (gating.py).

PanelState.emergency not NORMAL on a fresh, valid panel image is NONE, inhibited, code ESTOP, ahead
of the lease, the drives and every source. After NORMAL a hand input held through the E-stop and the
Reset stays dead until every hand input has read released once (RepressGuard / repress_gate). An
invalid or stale image stays PANEL_STALE's: a DIO link loss is not an E-stop press.
"""

import pytest

from amr_base import gating
from amr_base.gating import (
    FOLLOW,
    LEASE_AUTONOMOUS,
    LEASE_LINE,
    LEASE_MANUAL,
    LINE,
    MANUAL,
    NONE,
    PENDANT,
    TELEOP,
    Drives,
    Lease,
    Manual,
    Panel,
    Params,
    Permit,
    RepressGuard,
    Selection,
    Stamped,
    repress_gate,
    select,
)

NOW = 10.0
SUP = Params(require_supervisor=True)
LEASE = Lease(NOW, "i", 1, 1, LEASE_MANUAL | LEASE_AUTONOMOUS)
DRIVES = Drives(NOW, True)
JOG = Manual(NOW, 0.2, 0.0, "i", 1, "s", 1, 0.5)


@pytest.mark.parametrize("emg", [1, 2, 3, 4])
def test_estop_inhibits_every_source_ahead_of_the_lease(emg):
    manual = Panel(NOW, True, False, fwd=True, emergency=emg)
    s = select(NOW, Stamped(NOW, 0.3, 0.0), None, None, None, manual, SUP, lease=LEASE, manual=JOG,
               drives=DRIVES)
    assert (s.source, s.v, s.w, s.inhibited, s.code) == (NONE, 0.0, 0.0, True, "ESTOP")
    auto = Panel(NOW, True, True, emergency=emg)
    s = select(NOW, None, Stamped(NOW, 0.3, 0.0), None, Permit(NOW, FOLLOW, True, "i", 1), auto, SUP,
               lease=Lease(NOW, "i", 1, 1, 0), drives=Drives(NOW, False))
    assert s.code == "ESTOP", "ahead of INHIBITED / DRIVES_NOT_READY"
    s = select(NOW, None, None, None, None, auto, SUP, lease=Lease(NOW, "i", 1, 1, LEASE_LINE), drives=DRIVES,
               line=Stamped(NOW, 0.5, 0.0))
    assert (s.source, s.code) == (NONE, "ESTOP"), "the line follower too"
    s = select(NOW, Stamped(NOW, 0.3, 0.0), None, None, None, manual)  # unsupervised bench
    assert (s.source, s.code) == (NONE, "ESTOP")


def test_normal_changes_nothing():
    pendant = Panel(NOW, True, False, fwd=True)
    assert select(NOW, None, None, None, None, pendant, SUP, lease=LEASE, drives=DRIVES).source == PENDANT
    line = select(NOW, None, None, None, None, Panel(NOW, True, True), SUP,
                  lease=Lease(NOW, "i", 1, 1, LEASE_LINE), drives=DRIVES, line=Stamped(NOW, 0.5, 0.0))
    assert line.source == LINE


def test_an_invalid_or_stale_image_is_panel_stale_not_an_estop():
    """emergency plan §7.7: unplugging the DIO Ethernet reads PANEL_STALE, no motion."""
    s = select(NOW, None, None, None, None, Panel(NOW, False, False, emergency=1))
    assert (s.source, s.code) == (NONE, "PANEL_STALE")
    s = select(NOW, None, None, None, None, Panel(NOW - 1.0, True, False, fwd=True, emergency=1))
    assert (s.source, s.code) == (NONE, "PANEL_STALE")
    s = select(NOW, None, None, None, None, Panel(NOW + 0.5, True, False, emergency=1))  # future-stamped
    assert s.code == "PANEL_STALE"


def test_repress_guard_needs_one_release_after_normal():
    g = RepressGuard()
    assert not g.update(0, True), "a pendant held with no emergency is just driving"
    assert g.update(1, True)
    assert g.update(2, False), "released during the emergency does not count"
    assert g.update(0, True), "held through the Reset: nothing moves"
    assert not g.update(0, False)
    assert not g.update(0, True), "a fresh press after the release drives"


@pytest.mark.parametrize("src", ["pendant", "manual", "teleop"])
def test_a_hand_held_through_the_reset_does_not_drive_until_released(src):
    """emergency plan §7.1/§7.2: keep the pendant (or the browser jog, or teleop) held through
    release and Reset: the vehicle must not move. Let go once, press again: it drives."""
    g = RepressGuard()
    held = {"pendant": dict(fwd=True), "manual": {}, "teleop": {}}[src]
    jog = JOG if src == "manual" else None
    tel = Stamped(NOW, 0.3, 0.0) if src == "teleop" else None
    want = {"pendant": PENDANT, "manual": MANUAL, "teleop": TELEOP}[src]
    sel = Selection(want, 0.3, 0.0, src, 1)

    for emg in (1, 2, 3):  # pressed, released, resetting: the selection is ESTOP's anyway
        repress_gate(g, sel, NOW, Panel(NOW, True, False, emergency=emg, **held), jog, tel)
    out = repress_gate(g, sel, NOW, Panel(NOW, True, False, **held), jog, tel)  # NORMAL, still held
    assert (out.source, out.v, out.w, out.code) == (NONE, 0.0, 0.0, "NO_SOURCE")
    released = repress_gate(g, Selection(NONE, 0.0, 0.0, "MANUAL, no fresh command", 1, code="NO_SOURCE"),
                            NOW, Panel(NOW, True, False), None, None)
    assert released.source == NONE and not g.blocked
    assert repress_gate(g, sel, NOW, Panel(NOW, True, False, **held), jog, tel) is sel


def test_a_stale_or_zero_jog_counts_as_released():
    g = RepressGuard()
    g.update(1, True)
    old = Manual(NOW - 1.0, 0.2, 0.0, "i", 1, "s", 1, 0.5)
    zero = Stamped(NOW, 0.0, 0.0)
    repress_gate(g, Selection(NONE, 0.0, 0.0, "", 1), NOW, Panel(NOW, True, False), old, zero)
    assert not g.blocked


def test_auto_sources_are_not_held_by_the_repress_rule():
    """The run needs its own physical Start after NORMAL (executor / line job); the hand rule
    must not also eat an AUTO selection, or a resumed run would be refused for a stray jog."""
    g = RepressGuard()
    g.update(1, True)
    sel = Selection(LINE, 0.5, 0.0, "line", 1)
    assert repress_gate(g, sel, NOW, Panel(NOW, True, True, fwd=True), None, None) is sel
    assert g.blocked, "...but the hand stays blocked"


def test_no_panel_sample_is_select_s_refusal_already():
    g = RepressGuard()
    sel = Selection(NONE, 0.0, 0.0, "no panel authority", 0, code="PANEL_STALE")
    assert repress_gate(g, sel, NOW, None, None, None) is sel and not g.blocked


def test_the_estop_check_is_the_first_rule_in_select():
    """Static: the ESTOP return sits above the lease check, so no later rule can return first."""
    import inspect

    src = inspect.getsource(gating.select)
    assert 0 < src.index('code="ESTOP"') < src.index('code="NOT_LEASED"')
