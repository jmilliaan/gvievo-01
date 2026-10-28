"""P2 (unified plan §12.2): authority expires at both control layers, independently.

Pure, with an injected clock: gating.select is the mux's decision and
gating.drive_gate is the drive owner's. Neither may accept a nonzero command
without a fresh, matching supervisor lease; freshness returning does not
revive a cached command.
"""

from gating_fixtures import DRIVES_OK, INST, SUP, lease, panel

from amr_base import gating
from amr_base.gating import (
    FOLLOW,
    LEASE_MANUAL,
    MANUAL,
    NONE,
    TELEOP,
    Drives,
    Manual,
    Params,
    Permit,
    Stamped,
    drive_gate,
    nav_topic,
    select,
)


def manual(t, v=0.2, gen=3, inst=INST, valid=0.2, seq=5):
    return Manual(t=t, v=v, w=0.0, instance=inst, generation=gen, session="s1", seq=seq, valid_for_s=valid)


MANUAL_PANEL = panel()
AUTO_PANEL = panel(auto=True)


def test_manual_command_needs_fresh_lease_panel_and_drives():
    s = select(10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(10.0), DRIVES_OK)
    assert (s.source, s.v, s.generation, s.inhibited) == (MANUAL, 0.2, 3, False)
    # lease 0.35 s old: gate closed, inhibited, zero
    s = select(10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(9.65), manual(10.0), DRIVES_OK)
    assert (s.source, s.v, s.inhibited) == (NONE, 0.0, True)
    # lease present but no classes allowed (transition barrier)
    s = select(
        10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0, allowed=0), manual(10.0), DRIVES_OK
    )
    assert s.source == NONE and s.inhibited
    # drives stale / not operational
    s = select(10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(10.0), Drives(9.6, True))
    assert s.source == NONE and s.inhibited
    s = select(
        10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(10.0), Drives(10.0, False)
    )
    assert s.source == NONE and s.inhibited
    # no lease at all
    assert select(10.0, None, None, None, None, MANUAL_PANEL, SUP, None, manual(10.0), DRIVES_OK).inhibited


def test_expired_manual_command_is_zero_at_once_and_bounded_by_its_own_lifetime():
    # older than cmd_timeout: gone, no ramp-down of the previous value
    s = select(10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(9.75), DRIVES_OK)
    assert (s.source, s.v) == (NONE, 0.0)
    # carried lifetime shorter than the mux timeout wins
    s = select(
        10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(9.9, valid=0.05), DRIVES_OK
    )
    assert s.source == NONE
    s = select(
        10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(9.9, valid=0.15), DRIVES_OK
    )
    assert s.source == MANUAL


def test_freshness_recovery_cannot_replay_a_cached_command():
    """The lease comes back; the manual command received before the gap stays dead."""
    cmd = manual(10.0)
    assert (
        select(10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), cmd, DRIVES_OK).source == MANUAL
    )
    assert select(10.5, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), cmd, DRIVES_OK).inhibited
    # fresh lease again at 10.6; the cached command is 0.6 s old -> still zero
    s = select(10.6, None, None, None, None, MANUAL_PANEL, SUP, lease(10.6), cmd, Drives(10.6, True))
    assert (s.source, s.v, s.inhibited) == (NONE, 0.0, False)


def test_wrong_instance_or_generation_is_not_authority():
    s = select(
        10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0, gen=4), manual(10.0, gen=3), DRIVES_OK
    )
    assert s.source == NONE
    s = select(
        10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(10.0, inst="other"), DRIVES_OK
    )
    assert s.source == NONE
    # an executor permit from a replaced layer under AUTO
    follow = Stamped(10.0, 0.3, 0.0)
    old_permit = Permit(10.0, FOLLOW, True, INST, 2, 1)
    s = select(10.0, None, follow, None, old_permit, AUTO_PANEL, SUP, lease(10.0), None, DRIVES_OK)
    assert s.source == NONE and s.inhibited
    new_permit = Permit(10.0, FOLLOW, True, INST, 3, 1)
    s = select(10.0, None, follow, None, new_permit, AUTO_PANEL, SUP, lease(10.0), None, DRIVES_OK)
    assert (s.source, s.v) == (FOLLOW, 0.3)
    # AUTO class withheld by the supervisor
    s = select(
        10.0,
        None,
        follow,
        None,
        new_permit,
        AUTO_PANEL,
        SUP,
        lease(10.0, allowed=LEASE_MANUAL),
        None,
        DRIVES_OK,
    )
    assert s.source == NONE and s.inhibited


def test_engineering_teleop_is_off_in_production_and_on_at_the_bench():
    tele = Stamped(10.0, 0.3, 0.0)
    assert (
        select(10.0, tele, None, None, None, MANUAL_PANEL, SUP, lease(10.0), None, DRIVES_OK).source == NONE
    )
    bench = Params(require_supervisor=False)
    assert select(10.0, tele, None, None, None, MANUAL_PANEL, bench).source == TELEOP
    prod_with_tele = Params(require_supervisor=True, teleop_enabled=True)
    assert (
        select(
            10.0, tele, None, None, None, MANUAL_PANEL, prod_with_tele, lease(10.0), None, DRIVES_OK
        ).source
        == TELEOP
    )


def test_drive_owner_gate_is_independent_of_the_mux():
    sup = Params(require_supervisor=True)
    assert drive_gate(10.0, lease(10.0), 3, sup) is None
    assert drive_gate(10.0, None, 3, sup) == "no supervisor lease"
    assert drive_gate(10.4, lease(10.0), 3, sup) == "no supervisor lease"  # expired
    assert "inhibited" in drive_gate(10.0, lease(10.0, allowed=0), 3, sup)
    assert "generation" in drive_gate(10.0, lease(10.0, gen=4), 3, sup)  # a mux still on the old layer
    assert drive_gate(10.0, None, 0, Params(require_supervisor=False)) is None  # bench


def test_nav_topics_are_private_per_generation():
    assert nav_topic("/cmd_vel", 0) == "/cmd_vel"
    assert nav_topic("/cmd_vel", 7) == "/amr/layers/g7/cmd_vel"  # a token may not start with a digit
    assert nav_topic("/cmd_vel_rotate", 7) == "/amr/layers/g7/cmd_vel_rotate"
    assert gating.NAMES[MANUAL] == "manual"


def test_hand_driven_source_changes_are_not_operator_events():
    """A jog is a hundred edges: press and release flip manual <-> none. At 300 entries
    the event ring would hold nothing but somebody's thumb (vehicle, 2026-09-22)."""
    from amr_base.cmd_mux_kinematics_node import HAND_SOURCES

    def is_history(new, old, inhibited=False):
        return bool(inhibited or {new, old} - HAND_SOURCES)

    assert not is_history("manual", "none")  # jog press
    assert not is_history("none", "manual")  # jog release
    assert not is_history("none", "pendant")
    assert is_history("none", "follow")  # the executor losing the wheels IS history
    assert is_history("line", "none")
    assert is_history("none", "manual", inhibited=True)  # so is an inhibit


# -- WP-A5: a stamp from the future is not fresh ------------------------------------------
# A backward clock step used to leave samples stamped before it reading fresh for their whole
# limit plus the step. The mux now stamps with time.monotonic(), and an age below zero is
# stale whatever the clock: output goes to zero, the next fresh sample restores selection.

FUTURE = 10.5  # every input stamped half a second after `now`


def test_a_future_stamped_lease_closes_the_gate():
    s = select(10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(FUTURE), manual(10.0), DRIVES_OK)
    assert (s.source, s.v, s.inhibited) == (NONE, 0.0, True)


def test_a_future_stamped_panel_drives_or_command_is_not_fresh():
    s = select(10.0, None, None, None, None, panel(t=FUTURE), SUP, lease(10.0), manual(10.0), DRIVES_OK)
    assert s.source == NONE and s.v == 0.0
    s = select(10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(10.0),
               Drives(FUTURE, True))
    assert s.source == NONE and s.v == 0.0
    s = select(10.0, None, None, None, None, MANUAL_PANEL, SUP, lease(10.0), manual(FUTURE), DRIVES_OK)
    assert s.source == NONE and s.v == 0.0


def test_a_future_stamped_teleop_permit_or_line_command_is_not_fresh():
    from amr_base.gating import LEASE_LINE, Params

    tele = Params(require_supervisor=False, teleop_enabled=True)
    s = select(10.0, Stamped(FUTURE, 0.3, 0.0), None, None, None, MANUAL_PANEL, tele)
    assert s.v == 0.0
    s = select(10.0, None, Stamped(10.0, 0.3, 0.0), None, Permit(FUTURE, FOLLOW, True, INST, 3, 1),
               AUTO_PANEL, SUP, lease(10.0), None, DRIVES_OK)
    assert s.source == NONE and s.v == 0.0
    s = select(10.0, None, None, None, None, AUTO_PANEL, SUP, lease(10.0, allowed=LEASE_LINE), None,
               DRIVES_OK, line=Stamped(FUTURE, 0.2, 0.0))
    assert s.source == NONE and s.v == 0.0
    # and the next fresh sample restores selection: nothing latched
    s = select(10.6, None, None, None, None, panel(t=10.6, auto=True), SUP,
               lease(10.6, allowed=LEASE_LINE), None, Drives(10.6, True), line=Stamped(10.6, 0.2, 0.0))
    assert s.v == 0.2


def test_the_mux_stamps_with_the_monotonic_clock_and_ticks_on_steady_timers():
    """Contract: the mux's receipt clock is time.monotonic, and every motion-path tick runs on a
    STEADY timer (LeanNode.create_steady_timer)."""
    import inspect
    import pathlib

    from amr_base.cmd_mux_kinematics_node import CmdMuxKinematics

    assert "time.monotonic()" in inspect.getsource(CmdMuxKinematics._now)
    src = pathlib.Path(__file__).resolve().parents[2]
    for rel, tick in (("amr_base/amr_base/cmd_mux_kinematics_node.py", "self._tick"),
                      ("amr_base/amr_base/panel_node.py", "self._tick"),
                      ("amr_line/amr_line/line_follow_node.py", "self._tick"),
                      ("amr_mission/amr_mission/route_executor_node.py", "self._tick"),
                      ("amr_bringup/amr_bringup/supervisor_node.py", "self._publish_mode")):
        text = (src / rel).read_text(encoding="utf-8")
        assert "create_steady_timer(" in text and tick in text.split("create_steady_timer(", 1)[1][:120], rel


def test_the_gate_limits_are_the_profiles_and_the_consumers_sit_at_or_above_them():
    """WP-A10: one source for every freshness limit (the profile's freshness block). gating's
    pure defaults - what every unit test runs with - are the profile's gate values, and each
    consumer limit is at or above the gate it mirrors (the profile refuses otherwise)."""
    from agv_core import config

    d = gating.DEFAULT
    limits = (d.cmd_timeout_s, d.lease_timeout_s, d.permit_timeout_s, d.panel_timeout_s, d.drives_timeout_s)
    assert limits == (config.FRESH_CMD_S, config.FRESH_LEASE_S, config.FRESH_PERMIT_S,
                      config.FRESH_PANEL_S, config.FRESH_DRIVES_S)
    assert config.FRESH_CMD_S <= 0.2 and config.FRESH_LEASE_S <= 0.3 and config.FRESH_PERMIT_S <= 0.3
    for consumer, gate in ((config.FRESH_LINE_PANEL_S, config.FRESH_PANEL_S),
                           (config.FRESH_LINE_LEASE_S, config.FRESH_LEASE_S),
                           (config.FRESH_LINE_DRIVES_S, config.FRESH_DRIVES_S),
                           (config.FRESH_EXEC_PANEL_S, config.FRESH_PANEL_S),
                           (config.FRESH_EXEC_DRIVES_S, config.FRESH_DRIVES_S)):
        assert consumer >= gate


def test_the_mux_refuses_a_ros_param_override_above_a_ceiling():
    import inspect

    from amr_base.cmd_mux_kinematics_node import CmdMuxKinematics

    src = inspect.getsource(CmdMuxKinematics.__init__)
    assert '("cmd_timeout_s", 0.2), ("lease_timeout_s", 0.3), ("permit_timeout_s", 0.3)' in src
