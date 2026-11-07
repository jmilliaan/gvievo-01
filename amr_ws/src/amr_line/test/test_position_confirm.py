"""Automatic confirm at HOME (manuals/home-auto-confirm-plan.md): an At home press, and recovery of a LOST
monitor when parked at HOME. Pure, clock-fed."""

import dataclasses

import pytest
from agv_core import position_status as status

from amr_line import position_confirm as pc

HOME = (0.0, -1.2, -0.08)
PER_REV = 10000.0


def params(**over):
    base = {"at_home": True, "recover": True, "hold_s": 1.0, "timeout_s": 20.0, "max_offset_m": 1.0,
            "settle_s": 3.0, "retry_s": 60.0, "wheel_dia_m": 0.18}
    return pc.Params(**{**base, **over})


def good(now, **over):
    """Everything right, with the monitor and AMCL heard just now."""
    base = {"now": now, "monitor_state": pc.CHECKING, "monitor_t": now, "can_confirm": True,
            "scan_match": 0.94, "scan_long": 0.02, "job_idle": True, "tape_seen": True,
            "pose": (0.1, -1.2, -0.07), "pose_t": now,
            "home": HOME, "counts": (1000, 1000), "counts_per_rev": PER_REV, "parked_at_home": True,
            "wheels_still": True}
    return pc.Facts(**{**base, **over})


def run(p, t0, t1, **over):
    """Ticks every 0.1 s; (time, action) for each action."""
    out, t = [], t0
    while t <= t1 + 1e-9:
        act = p.tick(good(t, **over))
        if act:
            out.append((round(t, 1), act))
        t = round(t + 0.1, 1)
    return out


def pressed(**over):
    p = pc.PositionConfirm(params(**over))
    p.press(0.0, (1000, 1000))
    return p


# -- an At home press ------------------------------------------------------------------------------
def test_a_press_confirms_after_the_hold_and_only_once():
    p = pressed()
    acts = run(p, 0.1, 5.0)
    assert acts == [(1.1, pc.CONFIRM)], "1 s of good evidence, then one call"
    p.reply(5.0, True)
    assert not p.checking and p.detail == ""
    assert p.events[-1][0] == "info" and p.events[-1][1].startswith("position confirmed at home: match 94 %")
    assert run(p, 5.1, 9.0, monitor_state=pc.READY) == []


def test_no_press_no_confirm_however_good_the_scans():
    p = pc.PositionConfirm(params(recover=False))
    assert run(p, 0.0, 100.0) == [] and p.events == []


def test_a_latched_can_confirm_from_before_the_press_does_not_count():
    p = pc.PositionConfirm(params())
    p.press(5.0, (1000, 1000))
    assert run(p, 5.1, 15.0, monitor_t=4.9) == []
    assert "waiting for the monitor" in p.detail


def test_a_ready_from_before_the_press_does_not_end_it():
    p = pc.PositionConfirm(params())
    p.press(5.0, (1000, 1000))
    p.tick(good(5.1, monitor_state=pc.READY, monitor_t=4.9))
    assert p.checking


def test_an_amcl_pose_from_before_the_press_does_not_count():
    p = pc.PositionConfirm(params())
    p.press(5.0, (1000, 1000))
    assert run(p, 5.1, 10.0, pose_t=4.9) == []
    assert "AMCL" in p.detail


@pytest.mark.parametrize(
    "over, needle",
    [
        ({"monitor_state": pc.LOST}, "position lost"),
        ({"can_confirm": False}, "match 94 %"),
        ({"tape_seen": False}, "tape not seen"),
        ({"counts": None}, "wheel counts"),
        ({"pose": None}, "AMCL"),
        ({"pose": (1.5, -1.2, -0.08)}, "m from HOME"),
        ({"pose": (0.0, -1.2, 0.5)}, "heading"),
        ({"home": None}, "no taught HOME"),
    ],
    ids=["monitor", "scans", "tape", "counts", "no pose", "offset", "heading", "no home"],
)
def test_each_condition_alone_blocks_a_press_and_the_timeout_names_it(over, needle):
    p = pressed(recover=False)
    assert run(p, 0.1, 19.9, **over) == []
    assert p.checking and status.CHECKING in p.detail and needle in p.detail
    run(p, 20.0, 25.0, **over)
    assert not p.checking and p.detail.startswith(status.FAILED) and needle in p.detail
    assert p.events[-1][0] == "warn"


def test_a_failed_press_does_not_retry_by_itself():
    p = pressed(recover=False)
    run(p, 0.1, 21.0, can_confirm=False)
    assert run(p, 21.1, 300.0) == []


def test_a_dropout_restarts_the_hold():
    p = pressed()
    assert run(p, 0.1, 0.9) == []
    assert run(p, 1.0, 1.0, tape_seen=False) == []
    assert run(p, 1.1, 2.0) == []
    assert run(p, 2.1, 2.1) == [(2.1, pc.CONFIRM)]


@pytest.mark.parametrize(
    "over, needle",
    [({"counts": (1000, 3000)}, "wheels moved"), ({"reset_edge": True}, "Reset"),
     ({"job_idle": False}, "took over")],
    ids=["wheels", "reset", "job"],
)
def test_a_press_is_cancelled(over, needle):
    p = pressed()
    assert run(p, 0.1, 0.1, **over) == []
    assert not p.checking and p.detail.startswith(status.FAILED) and needle in p.detail


def test_a_refused_confirm_is_a_failure():
    p = pressed()
    run(p, 0.1, 1.1)
    p.reply(1.2, False, "cannot confirm: LOST")
    assert not p.checking and p.detail.startswith(status.FAILED) and "cannot confirm" in p.detail


def test_a_late_reply_changes_nothing():
    p = pressed()
    run(p, 0.1, 1.1)
    run(p, 1.2, 21.0)
    assert not p.checking
    detail = p.detail
    p.reply(30.0, True)
    assert p.detail == detail


def test_a_person_confirming_by_hand_ends_the_wait():
    p = pressed()
    assert p.tick(good(0.2, monitor_state=pc.READY)) == ""
    assert not p.checking and p.detail == "" and "by hand" in p.events[-1][1]


def test_the_switch_off_never_arms_a_press():
    p = pressed(at_home=False, recover=False)
    assert run(p, 0.1, 30.0) == [] and not p.checking


# -- recovery at home ------------------------------------------------------------------------------
LOST = {"monitor_state": pc.LOST, "can_confirm": False, "pose_t": -1.0, "monitor_t": -1.0}


def test_recovery_seeds_after_settling_then_confirms():
    p = pc.PositionConfirm(params())
    assert run(p, 10.0, 12.9, **LOST) == [] and p.detail == status.RECHECKING
    assert run(p, 13.0, 13.0, **LOST) == [(13.0, pc.SEED)]
    assert p.checking and p.events[-1][1].startswith("position lost at home")
    assert run(p, 13.1, 18.0) == [(14.1, pc.CONFIRM)]
    p.reply(18.0, True)
    assert not p.checking and p.detail == ""
    assert p.events[-1][1].startswith("position recovered at home: match 94 %")


def test_recovery_covers_a_lost_while_parked_with_no_selector_input():
    assert "panel" not in {f.name for f in dataclasses.fields(pc.Facts)}
    assert "selector" not in {f.name for f in dataclasses.fields(pc.Facts)}


@pytest.mark.parametrize(
    "over",
    [{"job_idle": False}, {"parked_at_home": False}, {"wheels_still": False}, {"tape_seen": False},
     {"monitor_state": pc.READY}, {"monitor_state": pc.UNLOCALIZED}, {"monitor_state": pc.CHECKING},
     {"monitor_state": None}],
    ids=["job", "not parked", "moving", "tape", "ready", "unlocalized", "hand pose", "no monitor"],
)
def test_each_condition_alone_blocks_the_start(over):
    p = pc.PositionConfirm(params())
    assert run(p, 0.0, 100.0, **{**LOST, **over}) == []
    assert not p.checking and p.detail == ""


def test_the_switch_off_never_recovers():
    p = pc.PositionConfirm(params(recover=False))
    assert run(p, 0.0, 100.0, **LOST) == [] and p.detail == ""


def test_a_failed_recovery_retries_only_after_the_gap_and_says_why():
    p = pc.PositionConfirm(params(retry_s=60.0))
    assert run(p, 0.0, 3.0, **LOST) == [(3.0, pc.SEED)]
    bad = {"can_confirm": False}
    assert run(p, 3.1, 23.0, **bad) == []       # timed out at 23 s
    assert not p.checking and p.detail.startswith(status.RECHECKING) and "scans not settled" in p.detail
    assert run(p, 23.1, 82.9, **bad) == []
    assert run(p, 83.0, 83.0, **bad) == [(83.0, pc.SEED)], "still CHECKING after its own attempt: again"


def test_retries_stop_when_a_condition_fails():
    p = pc.PositionConfirm(params())
    run(p, 0.0, 3.0, **LOST)
    run(p, 3.1, 23.0, can_confirm=False)
    assert run(p, 23.1, 300.0, can_confirm=False, parked_at_home=False) == []
    assert p.detail == ""


def test_a_recovery_is_cancelled_by_moving_or_leaving_home():
    for over in ({"counts": (1000, 3000)}, {"parked_at_home": False}, {"job_idle": False}):
        p = pc.PositionConfirm(params())
        run(p, 0.0, 3.0, **LOST)
        assert p.checking
        run(p, 3.1, 3.1, **over)
        assert not p.checking, over


def test_a_press_replaces_a_running_recovery():
    p = pc.PositionConfirm(params())
    run(p, 0.0, 3.0, **LOST)
    p.press(4.0, (1000, 1000))
    assert status.CHECKING in p.detail
    assert run(p, 4.1, 5.1) == [(5.1, pc.CONFIRM)]
    p.reply(5.2, True)
    assert p.events[-1][1].startswith("position confirmed at home")


def test_a_service_restart_clears_the_right_to_recover():
    p = pc.PositionConfirm(params())
    run(p, 0.0, 3.0, **LOST)
    run(p, 3.1, 23.0, can_confirm=False)
    p.tick(good(24.0, monitor_state=pc.UNLOCALIZED))
    assert run(p, 24.1, 200.0, monitor_state=pc.CHECKING) == [], "a pose set by hand needs a person"


def test_the_profile_gates_recovery_on_calling():
    import types

    v = types.SimpleNamespace(TAPE_LOC_AUTO_CONFIRM_HOME=True, TAPE_LOC_AUTO_RECOVER_HOME=True,
                              TAPE_LOC_CONFIRM_HOLD_S=1.0, TAPE_LOC_CONFIRM_TIMEOUT_S=20.0,
                              TAPE_LOC_CONFIRM_MAX_OFFSET_M=1.0, TAPE_LOC_RECOVER_SETTLE_S=3.0,
                              TAPE_LOC_RECOVER_RETRY_S=60.0, WHEEL_DIA_M=0.18)
    assert pc.Params.from_profile(v, calling=True).recover is True
    assert pc.Params.from_profile(v, calling=False).recover is False
    assert pc.Params.from_profile(v, calling=False).at_home is True
