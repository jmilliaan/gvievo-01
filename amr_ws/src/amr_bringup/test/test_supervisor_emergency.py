"""Emergency-suite plan Part B E4: the supervisor withholds the lease while PanelState.emergency is
not NORMAL (a second no-motion layer above the mux). No mode change; NORMAL gives the lease back,
which moves nothing by itself. Only a fresh panel image counts: a stale one is PANEL_STALE's.
Needs rclpy (the node module imports it), like test_hardness.
"""

import types

import pytest

pytest.importorskip("rclpy")

from amr_bringup import mode_fsm as fsm  # noqa: E402
from amr_bringup.readiness import Snapshots  # noqa: E402
from amr_bringup.supervisor_node import (  # noqa: E402
    EMERGENCY_FRESH_S,
    LEASE_LINE,
    LEASE_MANUAL,
    Supervisor,
)

NOW = 100.0


def _snap(emergency=0, age=0.0):
    """A real readiness.Snapshots fed one panel image `age` s before NOW (E5: the supervisor reads
    the emergency from the Snapshots, the value mode_fsm admission reads too)."""
    s = Snapshots()
    s.on_panel(types.SimpleNamespace(valid=True, mode_auto=False, emergency=emergency))
    s.panel_t = NOW - age
    return s


def _sv(mode, emergency=0, commissioning=False, age=0.0):
    snap = _snap(emergency, age)
    snap.commissioning_active = lambda now: commissioning
    sv = types.SimpleNamespace(
        txn=None, mode=mode, inhibit_manual=False, _exec_stale=False, snap=snap, _now=lambda: NOW,
    )
    sv._emergency = types.MethodType(Supervisor._emergency, sv)
    return sv


@pytest.mark.parametrize("emg", [1, 2, 3, 4])
def test_no_lease_in_any_mode_while_the_emergency_is_not_normal(emg):
    for mode in (fsm.LINE, fsm.NAVIGATION, fsm.IDLE, fsm.MAPPING):
        assert Supervisor._allowed(_sv(mode, emg)) == 0, mode
    assert Supervisor._allowed(_sv(fsm.IDLE, emg, commissioning=True)) == 0


def test_normal_gives_the_lease_back_unchanged():
    assert Supervisor._allowed(_sv(fsm.LINE)) == LEASE_MANUAL | LEASE_LINE
    assert Supervisor._allowed(_sv(fsm.IDLE)) == LEASE_MANUAL


def test_only_a_fresh_panel_image_counts():
    assert Supervisor._emergency(_sv(fsm.LINE, 1), NOW) == 1
    assert Supervisor._emergency(_sv(fsm.LINE, 1, age=EMERGENCY_FRESH_S + 0.1), NOW) == 0
    assert Supervisor._emergency(_sv(fsm.LINE, 1, age=-0.5), NOW) == 0, "future-stamped is not fresh"
    sv = _sv(fsm.LINE)
    sv.snap = Snapshots()  # no panel image yet
    assert Supervisor._emergency(sv, NOW) == 0
