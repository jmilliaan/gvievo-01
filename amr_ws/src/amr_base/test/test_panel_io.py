"""The real panel adapter (T12): edges, validity, and the horn rule, without ROS."""

from amr_base import panel_io
from amr_base.agv_repo import config

R, S, A = config.PANEL_DI_RESET, config.PANEL_DI_START, config.PANEL_DI_AUTO


def _di(reset=False, start=False, auto=False):
    bits = [False] * 16
    bits[R], bits[S], bits[A] = reset, start, auto
    return bits


def _snap(di, comms=True, detail="ok"):
    return {"comms_ok": comms, "di": di, "detail": detail}


def _adapter():
    return panel_io.PanelAdapter(debounce_scans=2)


def _settle(ad, di, n=2, comms=True):
    f = None
    for _ in range(n):
        f = ad.tick(_snap(di, comms))
    return f


def test_first_image_is_a_baseline_with_no_edges_even_if_start_is_held():
    """Anti-tie-down: a taped-down Start at power-on does nothing until released."""
    ad = _adapter()
    f = _settle(ad, _di(start=True, auto=True))
    assert f.valid and f.mode_auto and not f.start_edge and not f.reset_edge
    f = _settle(ad, _di(start=True, auto=True))
    assert not f.start_edge
    _settle(ad, _di(auto=True))  # release
    f = _settle(ad, _di(start=True, auto=True))  # press
    assert f.start_edge and not f.reset_edge


def test_edges_fire_once_and_need_debounce():
    ad = _adapter()
    _settle(ad, _di())
    f = ad.tick(_snap(_di(start=True)))  # one scan: not yet believed
    assert not f.start_edge and f.valid
    f = ad.tick(_snap(_di(start=True)))  # second scan: edge
    assert f.start_edge
    f = ad.tick(_snap(_di(start=True)))  # held: no repeat
    assert not f.start_edge
    f = _settle(ad, _di())  # release: no edge
    assert not f.start_edge
    f = _settle(ad, _di(reset=True))
    assert f.reset_edge and not f.start_edge


def test_comms_loss_invalidates_and_reconnect_rebaselines_without_an_edge():
    """Hazard 3 in core/panel.py: a button pressed during an outage is not a press."""
    ad = _adapter()
    f = _settle(ad, _di(auto=True))
    assert f.valid and f.mode_auto
    f = ad.tick(_snap(_di(auto=True), comms=False, detail="timeout"))
    assert not f.valid and not f.comms_ok
    assert "LOST" in f.changed and "invalid" in f.changed
    # comes back with Start already down and the selector moved
    f = _settle(ad, _di(start=True, auto=False))
    assert f.valid and not f.start_edge and not f.mode_auto
    # only a fresh press counts
    _settle(ad, _di(auto=False))
    f = _settle(ad, _di(start=True, auto=False))
    assert f.start_edge


def test_selector_level_and_seq_and_log_notes():
    ad = _adapter()
    f = _settle(ad, _di(auto=False))
    assert not f.mode_auto and "MANUAL" in (f.changed or "")
    f = _settle(ad, _di(auto=True))
    assert f.mode_auto and "AUTO" in f.changed
    f2 = ad.tick(_snap(_di(auto=True)))
    assert f2.seq == f.seq + 1 and f2.changed is None
    f = _settle(ad, _di(auto=True, start=True))
    assert "START edge" in f.changed


def test_malformed_image_is_not_a_press():
    ad = _adapter()
    _settle(ad, _di())
    f = ad.tick(_snap([True, True], comms=True))  # short image
    assert not f.valid and not f.start_edge


def test_horn_follows_commanded_motion_while_armed_on_a_fresh_command():
    h = panel_io.horn_wanted
    assert h(True, 1.0, 1.0, 0.0, 0.2)
    assert h(True, 0.0, -0.5, 0.1, 0.2)  # rotate in place counts as motion
    assert not h(True, 0.0, 0.0, 0.0, 0.2)  # armed, holding zero: no horn
    assert not h(False, 1.0, 1.0, 0.0, 0.2)  # not armed: cannot be moving
    assert not h(True, 1.0, 1.0, None, 0.2)  # never received a command
    assert not h(True, 1.0, 1.0, 0.3, 0.2)  # stale command is zero
