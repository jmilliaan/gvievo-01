"""Emergency-suite plan Part B E1/E3 (2026-11-16): the DI09 E-stop signal in the panel adapter, the
outputs while not NORMAL, the transition events, and the PanelState contract. Without ROS.
Owner 2026-11-16: DI09 HIGH = E-stop pressed, LOW / no signal = normal (informational); a DIO gap is
never an E-stop."""

import pathlib

import pytest
from agv_core import config

from amr_base import emergency, panel_io
from amr_base.emergency import ACTIVE, NORMAL, RESET_FAILED, RESET_NEEDED, RESETTING

E, F = config.PANEL_DI_ESTOP, config.PENDANT_DI_FWD
_ACQ = [0]


def _di(pressed=False, fwd=False):
    bits = [False] * 16
    bits[config.PANEL_DI_AUTO] = not config.PANEL_AUTO_WHEN_ON  # selector at MANUAL
    bits[E], bits[F] = pressed, fwd  # HIGH = pressed (panel.estop_active_high)
    return bits


def _snap(di, comms=True, new=True):
    if new:
        _ACQ[0] += 1
    return {"comms_ok": comms, "di": di, "detail": "ok", "rx_age_s": 0.01, "connected": True,
            "scans": _ACQ[0]}


def _adapter(**kw):
    # These tests are the signal path: on, whatever the profile says (both profiles bypass it
    # for now, emergency-suite plan §9). The bypass has its own tests below.
    kw.setdefault("estop_signal_enabled", True)
    return panel_io.PanelAdapter(debounce_scans=2, estop_confirm_scans=2, **kw)


def test_the_profile_bypasses_the_signal_for_now():
    """Owner 2026-11-17 (plan §9): DI09 read LOW with the E-stop pressed on agv-01's first run."""
    assert config.PANEL_ESTOP_SIGNAL_ENABLED is False
    assert panel_io.PanelAdapter().estop_signal_enabled is False


def test_a_bypassed_signal_is_never_read():
    """DI09 HIGH for ten valid scans: estop_ok stays True, no DI09 note, and the machine never
    leaves NORMAL. The raw level is ignored, not inverted."""
    ad, e = _adapter(estop_signal_enabled=False), emergency.Emergency(3.0)
    notes = []
    for k in range(10):
        f = ad.tick(_snap(_di(pressed=True)))
        notes.append(f.changed or "")
        assert f.estop_ok
        assert e.step(0.05 * k, emergency.Inputs(f.valid, f.estop_ok, f.reset_edge, True)) is None
    assert e.state == NORMAL
    assert not any("E-stop" in n for n in notes), notes
    for _ in range(3):
        f = ad.tick(_snap(_di(pressed=False)))
        assert f.estop_ok and "E-stop" not in (f.changed or "")


def test_panel_node_logs_the_bypass():
    src = pathlib.Path(panel_io.__file__).with_name("panel_node.py").read_text(encoding="utf-8")
    assert "PANEL_ESTOP_SIGNAL_ENABLED" in src and "BYPASSED" in src


def test_the_profile_wires_di09_active_high_with_a_two_scan_filter():
    assert config.PANEL_DI_ESTOP == 9 and config.PANEL_ESTOP_ACTIVE_HIGH is True
    assert (config.PANEL_ESTOP_CONFIRM_SCANS, config.PANEL_ESTOP_RESET_TIMEOUT_S) == (2, 3.0)
    ad = panel_io.PanelAdapter(estop_signal_enabled=True)
    assert (ad.estop_confirm_scans, ad.estop_active_high) == (2, True)


def test_active_needs_confirm_scans_and_clear_needs_debounce():
    """One HIGH scan (a Q3 test pulse) is not an emergency; two are. Clearing needs
    debounce_scans LOW scans."""
    ad = _adapter()
    f = ad.tick(_snap(_di()))
    f = ad.tick(_snap(_di()))  # the first valid image: clear, no boot-time emergency
    assert f.valid and f.estop_ok and "E-stop signal (DI09) clear" in f.changed
    f = ad.tick(_snap(_di(pressed=True)))
    assert f.estop_ok, "one HIGH scan is filtered"
    f = ad.tick(_snap(_di()))
    assert f.estop_ok and not f.changed
    ad.tick(_snap(_di(pressed=True)))
    f = ad.tick(_snap(_di(pressed=True)))
    assert not f.estop_ok and "E-stop signal (DI09) ACTIVE" in f.changed
    f = ad.tick(_snap(_di()))
    assert not f.estop_ok, "one LOW scan after a press is not believed"
    f = ad.tick(_snap(_di()))
    assert f.estop_ok
    f = ad.tick(_snap(_di(), new=False))  # the same acquisition republished
    assert f.estop_ok


def test_a_dio_gap_holds_the_signal_as_it_was():
    """Owner 2026-11-16: a stale or invalid image is never an E-stop, and never clears one."""
    ad = _adapter()
    for comms in (True, True, False, False, True, True):
        f = ad.tick(_snap(_di(), comms=comms))
        assert f.estop_ok, comms  # clear before, during and after the gap
    for _ in range(2):
        f = ad.tick(_snap(_di(pressed=True)))
    assert not f.estop_ok
    f = ad.tick(_snap(_di(), comms=False))
    assert not f.valid and not f.estop_ok, "pressed stays pressed while blind"


def test_a_broken_wire_reads_normal():
    """Owner 2026-11-16: LOW / no signal = normal. The signal is informational; STO is the
    Flexi Soft's in hardware, so the PC does not make a wire break an emergency."""
    ad = _adapter()
    for _ in range(4):
        f = ad.tick(_snap(_di(pressed=False)))
    assert f.valid and f.estop_ok


def test_the_polarity_is_the_profile_s():
    """A bench that finds the Flexi Soft driving Q3 the other way round flips
    panel.estop_active_high; no code change."""
    ad = _adapter(estop_active_high=False)
    for _ in range(3):
        f = ad.tick(_snap(_di(pressed=True)))  # DI09 HIGH = OK in that wiring
    assert f.valid and f.estop_ok
    for _ in range(2):
        f = ad.tick(_snap(_di(pressed=False)))
    assert not f.estop_ok


def test_a_pendant_held_through_the_emergency_is_masked_until_released():
    """emergency plan §7.1/§7.2 at the source (WP-A6's release-first rule): a direction held while
    the state is not NORMAL publishes idle until read LOW once, NORMAL or not."""
    ad = _adapter(pendant=True)
    for _ in range(2):
        ad.tick(_snap(_di()))
    f = ad.tick(_snap(_di(fwd=True)), normal=False)
    f = ad.tick(_snap(_di(fwd=True)), normal=False)
    assert not any(f.pendant) and "FWD held at enable: release it" in f.changed
    for _ in range(3):
        f = ad.tick(_snap(_di(fwd=True)), normal=True)  # NORMAL again, still held
        assert not any(f.pendant)
    for _ in range(2):
        ad.tick(_snap(_di()))
    for _ in range(2):
        f = ad.tick(_snap(_di(fwd=True)))
    assert f.pendant.fwd, "released, pressed again: drives"


def test_a_pendant_pressed_with_no_emergency_drives_at_once():
    ad = _adapter(pendant=True)
    for _ in range(2):
        ad.tick(_snap(_di()))
    for _ in range(2):
        f = ad.tick(_snap(_di(fwd=True)))
    assert f.pendant.fwd


def test_every_coil_is_low_while_not_normal():
    """Owner (emergency plan §4): no movement horn, no alarm horn, no pre-move warning, no stop
    call pulse, no DO08 while not NORMAL; at NORMAL the motion/alarm rules are unchanged."""
    kw = dict(alarm_on=[1], motion_on=[0, 8], movement_horn=[0])
    assert panel_io.coil_image(True, True, True, **kw) == {1: True, 0: False, 8: True}
    assert panel_io.coil_image(True, False, True, **kw) == {1: False, 0: True, 8: True}
    for alarm in (False, True):
        for turning in (False, True):
            assert panel_io.coil_image(False, alarm, turning, **kw) == {1: False, 0: False, 8: False}
    assert set(panel_io.coil_image(False, True, True)) == set(config.DIO_ALARM_ON) | set(config.DIO_MOTION_ON)


@pytest.mark.parametrize("state,prev,want", [
    (ACTIVE, NORMAL, ("error", "ESTOP")),
    (RESET_NEEDED, ACTIVE, ("warn", "ESTOP_RESET_NEEDED")),
    (RESETTING, RESET_NEEDED, ("info", "ESTOP")),
    (RESET_FAILED, RESETTING, ("error", "ESTOP_RESET_FAILED")),
    (NORMAL, RESETTING, ("info", "ESTOP")),
])
def test_each_transition_has_its_event(state, prev, want):
    ev = panel_io.emergency_event(state, prev, "emergency X -> Y: E-stop pressed")
    assert (ev[:2] if ev else None) == want
    if want == ("error", "ESTOP"):
        assert "EMERGENCY STOP (E-stop pressed)" in ev[2] and "press Reset" in ev[2]


def test_event_codes_are_catalogue_rows():
    from agv_core import alarms

    for code in ("ESTOP", "ESTOP_RESET_NEEDED", "ESTOP_RESET_FAILED", "ESTOP_HOLD"):
        assert code in alarms.CATALOGUE, code
    assert alarms.CATALOGUE["ESTOP_RESET_NEEDED"].clears_by == "reset_button"
    assert alarms.BUTTON["reset_button"] == "", "physical Reset only, never a web button"


def test_a_transition_is_published_on_its_tick():
    """RESETTING -> NORMAL lands on a DriveStatus, RESET_FAILED on time: between acquisitions."""
    gate = panel_io.PublishGate()
    idle = panel_io.PanelFrame(True, False, False, False, 1, True)
    assert gate.due(0.0, idle)
    assert not gate.due(0.02, idle)
    assert gate.due(0.021, idle, force=True)
    assert not gate.due(0.04, idle), "the forced publish restarts the fallback"


def test_the_machine_runs_on_the_adapter_s_frames():
    """Unlatched Q3, end to end on PanelFrames: press, release, Reset, drives out of STO."""
    ad, e = _adapter(), emergency.Emergency(3.0)
    t = [0.0]

    def step(pressed, sto=False, reset=False):
        t[0] += 0.05
        f = ad.tick(_snap(_di(pressed=pressed)))
        return e.step(t[0], emergency.Inputs(f.valid, f.estop_ok, reset or f.reset_edge, sto))

    step(False)
    step(False)
    assert e.state == NORMAL
    step(True, sto=True)
    assert e.state == NORMAL, "one HIGH scan"
    step(True, sto=True)
    assert e.state == ACTIVE
    step(False, sto=True)
    step(False, sto=True)
    assert e.state == RESET_NEEDED
    step(False, sto=True, reset=True)
    assert e.state == RESETTING
    step(False, sto=False)
    assert e.state == NORMAL


def test_panel_state_appends_the_kyb_contract():
    msg = pathlib.Path(panel_io.__file__).parents[2] / "amr_interfaces" / "msg" / "PanelState.msg"
    lines = [ln.split("#")[0].split() for ln in msg.read_text(encoding="utf-8").splitlines()]
    fields = [ln for ln in lines if ln and "=" not in ln[1]]
    assert fields[-2:] == [["bool", "estop_ok"], ["uint8", "emergency"]], "appended: never inserted"
    consts = {ln[1].split("=")[0]: int(ln[1].split("=")[1]) for ln in lines if ln and "=" in ln[1]}
    assert consts == {"EMG_NORMAL": 0, "EMG_ACTIVE": 1, "EMG_RESET_NEEDED": 2, "EMG_RESETTING": 3,
                      "EMG_RESET_FAILED": 4}
    assert (emergency.NORMAL, emergency.ACTIVE, emergency.RESET_NEEDED, emergency.RESETTING,
            emergency.RESET_FAILED) == (0, 1, 2, 3, 4)


def test_panel_node_wiring():
    """Static (the node needs rclpy): the machine runs every tick on the frame, its state rides
    PanelState, the coils go through coil_image, and the pendant mask follows the state."""
    src = (pathlib.Path(panel_io.__file__).parent / "panel_node.py").read_text(encoding="utf-8")
    assert "self._emergency_step(frame, now)" in src
    assert "m.estop_ok, m.emergency = frame.estop_ok, self.emergency.state" in src
    assert "panel_io.coil_image(normal, alarm," in src and "set_coil(ch, alarm" not in src
    assert "adapter.tick(snap, normal=self.emergency.state == emergency.NORMAL)" in src
    assert "hazard = normal and" in src and "call = normal and" in src
    assert "force=moved" in src
