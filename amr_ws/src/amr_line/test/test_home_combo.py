"""At home from the panel: Start + Reset held 1 s under MANUAL (amr_line.home_combo, 2026-11-11)."""
from amr_line import home_combo as hc

DT = 0.02          # the panel's 50 Hz


class Panel:
    """Levels in, edges derived the way PanelScan does (a rising level after the baseline)."""

    def __init__(self, combo, start=False, reset=False, auto=False):
        self.c, self.t = combo, 0.0
        self.start, self.reset, self.auto, self.valid = start, reset, auto, True

    def run(self, seconds, start=None, reset=None, auto=None, valid=None, edges=True):
        fired = 0
        new = (self.start if start is None else start, self.reset if reset is None else reset)
        se, re = edges and new[0] and not self.start, edges and new[1] and not self.reset
        self.start, self.reset = new
        self.auto = self.auto if auto is None else auto
        self.valid = self.valid if valid is None else valid
        for k in range(max(1, round(seconds / DT))):
            fired += self.c.tick(self.t, self.valid, self.auto, self.start, self.reset, se and k == 0,
                                 re and k == 0)
            self.t += DT
        return fired


def test_both_held_one_second_under_manual_fires_once():
    p = Panel(hc.HomeCombo())
    assert p.run(0.5, start=True) == 0
    assert p.run(0.9, reset=True) == 0, "1 s counts from the second button"
    assert p.run(0.2) == 1
    assert p.run(3.0) == 0, "once per hold"
    assert p.run(0.1, start=False) == 0
    assert p.run(1.5, start=True) == 0, "a new hold needs both let go"
    assert p.run(0.1, start=False, reset=False) == 0
    assert p.run(1.1, start=True, reset=True) == 1


def test_a_short_hold_or_one_button_does_nothing():
    p = Panel(hc.HomeCombo())
    assert p.run(0.9, start=True, reset=True) == 0
    assert p.run(0.1, reset=False) == 0
    assert p.run(5.0) == 0, "Start alone"
    assert p.run(0.1, start=False) == 0
    assert p.run(5.0, reset=True) == 0, "Reset alone"


def test_never_under_auto_or_on_a_bad_image():
    p = Panel(hc.HomeCombo(), auto=True)
    assert p.run(3.0, start=True, reset=True) == 0, "AUTO: Start is a motion command, not this"
    assert p.run(3.0, auto=False) == 0, "to MANUAL while held: the edges were under AUTO, they do not count"
    p = Panel(hc.HomeCombo())
    assert p.run(0.6, start=True, reset=True) == 0
    assert p.run(0.1, valid=False) == 0
    assert p.run(2.0, valid=True) == 0, "an invalid image breaks the hold; the levels came back without edges"
    p = Panel(hc.HomeCombo())
    assert p.run(0.6, start=True, reset=True) == 0
    assert p.run(2.0, auto=True) == 0, "the selector to AUTO mid-hold"


def test_buttons_held_since_power_on_never_count():
    p = Panel(hc.HomeCombo())
    assert p.run(5.0, start=True, reset=True, edges=False) == 0, "no edge seen: tied down"
    assert p.run(0.1, start=False) == 0
    assert p.run(1.1, start=True) == 0, "Reset still has no edge of its own"
    assert p.run(0.1, reset=False) == 0
    assert p.run(1.1, reset=True) == 1
