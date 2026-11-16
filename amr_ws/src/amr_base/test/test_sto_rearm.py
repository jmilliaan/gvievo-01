"""amr_base.sto_rearm (emergency-suite plan Part B E5 risk, 2026-11-16): after an E-stop Reset the
standby drives are taken out of Switch on disabled with Shutdown, so the emergency machine can reach
NORMAL instead of RESET_FAILED. With fakes: the drive is a CiA-402 state, the Reset the panel's
RESETTING state. Pure: no rclpy."""

from amr_base import emergency
from amr_base.sto_rearm import PERIOD_S, StoRearm

SOD, RTSO = emergency.STO_STATE, "Ready to switch on"


class FakeDrives:
    """Two BLV-R drives: STO holds Switch on disabled; Shutdown with STO released -> Ready to switch on."""

    def __init__(self):
        self.sto = True
        self.state = {1: SOD, 2: SOD}
        self.writes = []

    def shutdown(self, node):
        self.writes.append(node)
        if not self.sto:
            self.state[node] = RTSO


def test_the_standby_estop_reaches_normal_after_reset():
    """The failure mode it removes: E-stop pressed and released with the drives in standby. Before,
    nothing sent Shutdown, sto_held() stayed True and RESETTING ended RESET_FAILED."""
    d, r, e = FakeDrives(), StoRearm(), emergency.Emergency(3.0)
    t = 0.0
    e.step(t, emergency.Inputs(True, False, False, True))       # pressed: ACTIVE
    t += 0.1
    e.step(t, emergency.Inputs(True, True, False, True))        # released: RESET_NEEDED
    assert e.state == emergency.RESET_NEEDED
    t += 0.1
    e.step(t, emergency.Inputs(True, True, True, True))         # Reset: RESETTING
    assert e.state == emergency.RESETTING
    d.sto = False                                               # the Flexi Soft lets go of STO
    for _ in range(10):
        t += 0.1
        for n in r.due(t, e.state, "standby", d.state):
            d.shutdown(n)
        sto = emergency.sto_held(d.state[1], d.state[2], "standby", 0.05)
        e.step(t, emergency.Inputs(True, True, False, sto))
    assert e.state == emergency.NORMAL and d.state == {1: RTSO, 2: RTSO}
    assert d.writes == [1, 2], "one Shutdown each"


def test_without_it_the_reset_fails_as_the_risk_said():
    e = emergency.Emergency(3.0)
    e.step(0.0, emergency.Inputs(True, False, False, True))
    e.step(0.1, emergency.Inputs(True, True, False, True))
    e.step(0.2, emergency.Inputs(True, True, True, True))
    e.step(3.3, emergency.Inputs(True, True, False, True))  # nobody sent Shutdown: STO still read
    assert e.state == emergency.RESET_FAILED


def test_sto_released_late_is_retried_every_period():
    r = StoRearm()
    states = {1: SOD, 2: SOD}
    assert r.due(0.0, emergency.RESETTING, "standby", states) == [1, 2]
    assert r.due(0.1, emergency.RESETTING, "standby", states) == []
    assert r.due(PERIOD_S, emergency.RESETTING, "standby", states) == [1, 2]


def test_nothing_is_sent_outside_resetting_or_standby():
    r = StoRearm()
    states = {1: SOD, 2: SOD}
    for emg in (emergency.NORMAL, emergency.ACTIVE, emergency.RESET_NEEDED, emergency.RESET_FAILED):
        assert r.due(0.0, emg, "standby", states) == [], "a pressed E-stop is never written to"
    for link in ("armed", "disarmed", "fault"):
        assert r.due(0.0, emergency.RESETTING, link, states) == []


def test_only_the_drives_still_in_switch_on_disabled():
    r = StoRearm()
    assert r.due(0.0, emergency.RESETTING, "standby", {1: RTSO, 2: SOD}) == [2]
    assert StoRearm().due(0.0, emergency.RESETTING, "standby", {1: RTSO, 2: RTSO}) == []


def test_a_new_reset_starts_a_new_episode():
    r = StoRearm()
    states = {1: SOD, 2: SOD}
    assert r.due(0.0, emergency.RESETTING, "standby", states)
    assert r.due(0.1, emergency.RESET_FAILED, "standby", states) == []
    assert r.due(0.2, emergency.RESETTING, "standby", states) == [1, 2], "Reset again: at once"
