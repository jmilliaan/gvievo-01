from amr_base.gating import FOLLOW, NONE, ROTATE, TELEOP, Panel, Permit, Stamped, select

MANUAL = Panel(t_recv=10.0, valid=True, auto=False)
AUTO = Panel(t_recv=10.0, valid=True, auto=True)


def test_no_panel_no_motion():
    assert select(10.0, Stamped(10.0, 0.3, 0.0), None, None, None, None).source == NONE
    stale = Panel(t_recv=9.7, valid=True, auto=False)
    assert select(10.0, Stamped(10.0, 0.3, 0.0), None, None, None, stale).source == NONE
    invalid = Panel(t_recv=10.0, valid=False, auto=False)
    assert select(10.0, Stamped(10.0, 0.3, 0.0), None, None, None, invalid).source == NONE


def test_teleop_only_under_manual():
    s = select(10.0, Stamped(9.9, 0.3, 0.1), None, None, None, MANUAL)
    assert (s.source, s.v, s.w) == (TELEOP, 0.3, 0.1)
    s = select(10.0, Stamped(9.9, 0.3, 0.1), None, None, None, AUTO)
    assert s.source == NONE and s.v == 0.0


def test_teleop_window_does_not_extend_motion():
    # 0.35 s old: still owns the mux (0.5 s window) but the command has timed out (0.2 s)
    s = select(
        10.0, Stamped(9.65, 0.3, 0.0), Stamped(10.0, 0.3, 0.0), None, Permit(10.0, FOLLOW, True), MANUAL
    )
    assert s.source == TELEOP and s.v == 0.0
    # 0.6 s old: window gone, and under MANUAL the follow permit is not honoured either
    s = select(
        10.0, Stamped(9.4, 0.3, 0.0), Stamped(10.0, 0.3, 0.0), None, Permit(10.0, FOLLOW, True), MANUAL
    )
    assert s.source == NONE


def test_auto_needs_a_fresh_enabled_permit_matching_the_source():
    follow, rotate = Stamped(10.0, 0.3, 0.0), Stamped(10.0, 0.0, 0.3)
    assert select(10.0, None, follow, rotate, None, AUTO).source == NONE
    assert select(10.0, None, follow, rotate, Permit(9.6, FOLLOW, True), AUTO).source == NONE  # expired
    assert select(10.0, None, follow, rotate, Permit(10.0, FOLLOW, False), AUTO).source == NONE
    s = select(10.0, None, follow, rotate, Permit(10.0, FOLLOW, True), AUTO)
    assert (s.source, s.v) == (FOLLOW, 0.3)
    s = select(10.0, None, follow, rotate, Permit(10.0, ROTATE, True), AUTO)
    assert (s.source, s.w) == (ROTATE, 0.3)
    s = select(10.0, None, Stamped(9.7, 0.3, 0.0), rotate, Permit(10.0, FOLLOW, True), AUTO)
    assert s.source == NONE and "fresh" in s.reason


def test_teleop_command_is_ignored_under_auto_even_with_permit():
    s = select(10.0, Stamped(10.0, 0.5, 0.0), Stamped(10.0, 0.3, 0.0), None, Permit(10.0, FOLLOW, True), AUTO)
    assert (s.source, s.v) == (FOLLOW, 0.3)
