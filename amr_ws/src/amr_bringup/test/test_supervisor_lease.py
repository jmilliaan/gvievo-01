"""ControlLease.allowed bits per mode, and the requests a trackless vehicle admits.
Ported from test_tracked_product.py when LINE mode was retired (removal plan P1)."""

import types

from amr_bringup import mode_fsm as fsm
from amr_bringup.supervisor_node import LEASE_AUTONOMOUS, LEASE_COMMISSIONING, LEASE_MANUAL, Supervisor


def cond(**kw):
    base = dict(
        now=100.0,
        wheels_t=100.0,
        wheels_still_since=99.0,
        panel_t=100.0,
        panel_valid=True,
        panel_manual=True,
        run_state=fsm.RUN_IDLE,
        survey_state=None,
    )
    base.update(kw)
    return fsm.Conditions(**base)


def allowed(mode, txn=None, inhibit_manual=False, commissioning=False):
    sv = types.SimpleNamespace(
        txn=txn,
        mode=mode,
        inhibit_manual=inhibit_manual,
        snap=types.SimpleNamespace(commissioning_active=lambda now: commissioning),
        _now=lambda: 100.0,
    )
    return Supervisor._allowed(sv)


def test_lease_bits_per_mode():
    assert (LEASE_MANUAL, LEASE_AUTONOMOUS, LEASE_COMMISSIONING) == (1, 2, 4)
    assert allowed(fsm.NAVIGATION) == LEASE_MANUAL | LEASE_AUTONOMOUS
    assert allowed(fsm.IDLE) == LEASE_MANUAL
    assert allowed(fsm.IDLE, commissioning=True) == LEASE_COMMISSIONING
    assert allowed(fsm.MAPPING) == LEASE_MANUAL
    # inhibited: a transaction in flight, an unstable mode, or a save
    assert allowed(fsm.NAVIGATION, txn=object()) == 0
    for mode in (fsm.STARTING, fsm.TRANSITIONING, fsm.FAULT, fsm.STOPPING):
        assert allowed(mode) == 0
    assert allowed(fsm.NAVIGATION, inhibit_manual=True) == 0
    # bit 8 was LINE: retired, never set again
    for mode in fsm.MODE_NAMES:
        for c in (False, True):
            assert not allowed(mode, commissioning=c) & 8


def test_a_trackless_vehicle_admits_navigation_and_a_survey():
    assert fsm.admit(fsm.IDLE, fsm.REQ_NAVIGATION, cond()).ok
    assert fsm.admit(fsm.IDLE, fsm.REQ_SURVEY_START, cond()).ok
