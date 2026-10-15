"""aop-demo-oct: the web app's arm latch (amr_base/web_panel_node.WebArm). Pure, clock-fed."""

from amr_base.web_panel_node import Drives, WebArm


def test_boots_disarmed_and_refuses_to_arm_without_a_drive_status():
    a = WebArm(drives_timeout_s=1.0)
    assert a.armed is False
    ok, why = a.request(True, now=10.0)
    assert not ok and "no drive status" in why and a.armed is False


def test_arms_from_standby_and_disarms_on_request():
    a = WebArm()
    a.on_drives(Drives(10.0, "standby"))
    assert a.request(True, now=10.2) == (True, a.request(True, now=10.2)[1]) and a.armed
    ok, msg = a.request(False, now=10.3)
    assert ok and msg == "disarmed" and not a.armed
    assert a.request(False, now=10.4) == (True, "already disarmed")


def test_a_stale_or_faulted_drive_status_refuses_the_arm():
    a = WebArm(drives_timeout_s=1.0)
    a.on_drives(Drives(10.0, "standby"))
    assert not a.request(True, now=11.5)[0]  # stale
    a.on_drives(Drives(12.0, "fault"))
    ok, why = a.request(True, now=12.1)
    assert not ok and "fault" in why
    a.on_drives(Drives(12.2, "disarmed"))  # the link is down, nothing to power
    assert not a.request(True, now=12.3)[0]


def test_a_drive_fault_drops_the_arm_and_it_stays_dropped():
    """No automatic restart: after the fault clears, power needs a new Arm."""
    a = WebArm()
    a.on_drives(Drives(10.0, "standby"))
    a.request(True, now=10.1)
    a.on_drives(Drives(10.2, "armed"))
    assert a.armed
    why = a.on_drives(Drives(10.3, "fault"))
    assert why and not a.armed
    assert a.on_drives(Drives(11.0, "standby")) is None and not a.armed


def test_an_arm_the_drives_never_honour_is_dropped_before_drive_node_retries():
    """2026-10-15: one drive held in Switch on disabled made drive_node's 2 s engage retry
    enable and shut down the other drive over and over (audible clicking). One press of Arm
    is one attempt."""
    a = WebArm(engage_timeout_s=1.5)
    a.on_drives(Drives(10.0, "standby"))
    a.request(True, now=10.0)
    assert a.on_drives(Drives(10.5, "standby", operational=False)) is None and a.armed
    assert a.on_drives(Drives(11.4, "standby", operational=False)) is None and a.armed
    why = a.on_drives(Drives(11.6, "standby", operational=False))
    assert why and "did not power up" in why and not a.armed


def test_powered_drives_keep_the_arm_and_a_later_dropout_drops_it():
    a = WebArm(engage_timeout_s=1.5)
    a.on_drives(Drives(10.0, "standby"))
    a.request(True, now=10.0)
    for t in (10.4, 11.0, 12.0, 13.0, 14.0):
        assert a.on_drives(Drives(t, "armed", operational=True)) is None and a.armed
    assert a.on_drives(Drives(14.5, "standby", operational=False)) is None and a.armed
    assert a.on_drives(Drives(15.6, "standby", operational=False)) and not a.armed


def test_a_drive_status_that_stops_arriving_drops_the_arm_on_the_tick():
    a = WebArm(engage_timeout_s=1.5)
    a.on_drives(Drives(10.0, "standby"))
    a.request(True, now=10.0)
    a.on_drives(Drives(10.4, "armed", operational=True))
    assert a.tick(11.0) is None and a.armed
    assert a.tick(12.0) and not a.armed
