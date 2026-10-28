"""readiness.drive_ack_refusal: when Recover may acknowledge a drive-link fault (WP-B4)."""


def test_a_drive_fault_is_acknowledged_only_when_no_run_holds_the_drives():
    """WP-B4: Recover acknowledges a drive-link FAULT, but not under a run that still holds or
    asks for the drives. The drive_fault hold itself (unpowered) is when it is meant to be used."""
    import time
    from types import SimpleNamespace as NS

    from amr_bringup import readiness as rd

    def drives(link):
        return NS(operational=False, link_state=link, left_state="Fault", right_state="Fault")

    s = rd.Snapshots()
    now = time.monotonic()
    s.on_drives(drives("standby"))
    assert rd.drive_ack_refusal(s, now, 3) == "", "no fault: nothing to refuse"
    s.on_drives(drives("fault"))
    assert rd.drive_ack_refusal(s, now, 3) == ""
    s.on_line(NS(generation=3, state=2, drive_power=True))  # RUNNING
    assert "line run" in rd.drive_ack_refusal(s, now, 3)
    s.on_line(NS(generation=3, state=3, drive_power=True))  # a powered HOLD (the field)
    assert "line run" in rd.drive_ack_refusal(s, now, 3)
    s.on_line(NS(generation=3, state=3, drive_power=False))  # the drive_fault hold
    assert rd.drive_ack_refusal(s, now, 3) == ""
    s.on_run(NS(generation=3, state=2, drive_power=True, mission_id="m"))
    assert "trackless run" in rd.drive_ack_refusal(s, now, 3)
    assert rd.drive_ack_refusal(s, now + 5.0, 3) == "no fresh drive report"
