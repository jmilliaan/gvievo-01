"""/amr/panel_state once per DIO acquisition + a 50 ms fallback (unified plan WP-C3, cpu-load plan C#8).

A fake clock drives panel_node's loop as it runs: a 50 Hz tick reads the newest DIO snapshot (20 Hz
scans, with jitter and a phase), the adapter evaluates it, PublishGate decides whether it goes out.
What the consumers rely on is pinned here: every Start / Reset edge reaches the topic exactly once,
the topic never goes quiet for more than 60 ms, and the At home combination (amr_line.home_combo,
fed the published messages the way line_follow_node is) still fires within HOLD_S + 50 ms.
"""

import random

import pytest
from agv_core import config

from amr_base import panel_io

R, S, A = config.PANEL_DI_RESET, config.PANEL_DI_START, config.PANEL_DI_AUTO
TICK_S = 0.02  # panel_node rate_hz 50
SCAN_S = 0.05  # dio.scan_period_s 20 Hz


def _di(start=False, reset=False):
    bits = [False] * 16
    bits[R], bits[S] = reset, start
    bits[A] = not config.PANEL_AUTO_WHEN_ON  # selector at MANUAL (the At home combination needs it)
    return bits


def run(buttons, until_s, phase_s=0.0, jitter_s=0.0, seed=1, drop=()):
    """Simulate panel_node. buttons(t) -> (start, reset) physical levels at time t. drop: (t0, t1)
    windows with no successful scan (the image ages; comms stay ok until the source age).
    -> (published [(t, frame)], every frame [(t, frame)])."""
    rng = random.Random(seed)
    ad = panel_io.PanelAdapter(debounce_scans=2, pendant=False)
    gate = panel_io.PublishGate()
    scans, image, image_t = 0, _di(), None
    next_scan = phase_s
    pub, every = [], []
    t = 0.0
    while t <= until_s:
        while next_scan <= t:  # the scan thread's acquisitions up to now
            if not any(a <= next_scan < b for a, b in drop):
                scans += 1
                image, image_t = _di(*buttons(next_scan)), next_scan
            next_scan += SCAN_S + rng.uniform(-jitter_s, jitter_s)
        age = None if image_t is None else t - image_t
        snap = {"comms_ok": image_t is not None, "di": image, "detail": "ok", "rx_age_s": age,
                "connected": True, "scans": scans}
        f = ad.tick(snap)
        every.append((t, f))
        if gate.due(t, f):
            pub.append((t, f))
        t = round(t + TICK_S, 9)
    return pub, every


def presses(t_on, t_off, which="start"):
    def buttons(t):
        held = t_on <= t < t_off
        return (held, False) if which == "start" else (False, held)
    return buttons


@pytest.mark.parametrize("phase", [0.0, 0.003, 0.011, 0.019, 0.037])
def test_every_edge_is_published_exactly_once(phase):
    def buttons(t):  # three Start presses and two Reset presses, 0.3 s each
        start = any(a <= t < a + 0.3 for a in (0.5, 1.3, 2.1))
        reset = any(a <= t < a + 0.3 for a in (0.9, 1.7))
        return start, reset

    pub, every = run(buttons, 3.0, phase_s=phase, jitter_s=0.004, seed=int(phase * 1000))
    assert sum(f.start_edge for _, f in pub) == 3 == sum(f.start_edge for _, f in every)
    assert sum(f.reset_edge for _, f in pub) == 2 == sum(f.reset_edge for _, f in every)
    # each edge on the tick that evaluated it, never a republish of it
    edge_ticks = [t for t, f in every if f.start_edge or f.reset_edge]
    assert edge_ticks == [t for t, f in pub if f.start_edge or f.reset_edge]


@pytest.mark.parametrize("phase", [0.0, 0.007, 0.013, 0.029])
def test_the_worst_case_gap_is_60_ms(phase):
    pub, every = run(presses(0.5, 0.8), 3.0, phase_s=phase, jitter_s=0.005, seed=7)
    times = [t for t, _ in pub]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert max(gaps) <= 0.060 + 1e-9, max(gaps)
    # and it is a cut: fewer messages than ticks (20 Hz scans in a 50 Hz loop)
    assert len(pub) < 0.75 * len(every)


def test_a_stalled_scan_still_publishes_on_the_fallback():
    """No new acquisition for 0.4 s: the last frame repeats every <= 60 ms until the image ages out."""
    pub, _ = run(presses(5.0, 5.1), 2.0, drop=((1.0, 1.4),))
    times = [t for t, _ in pub if 1.0 <= t <= 1.5]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert gaps and max(gaps) <= 0.060 + 1e-9


def test_a_frame_that_changes_anything_goes_out_on_its_tick():
    gate = panel_io.PublishGate()
    quiet = panel_io.PanelFrame(valid=True, mode_auto=False, start_edge=False, reset_edge=False, seq=1,
                                comms_ok=True)
    assert gate.due(0.0, quiet)  # the first frame
    assert not gate.due(0.02, quiet)
    lost = panel_io.PanelFrame(valid=False, mode_auto=False, start_edge=False, reset_edge=False, seq=2,
                               comms_ok=False, changed="DIO comms LOST (timeout); panel image invalid")
    assert gate.due(0.03, lost)  # the invalid edge is not held back for the fallback
    assert not gate.due(0.05, quiet)
    assert gate.due(0.079, quiet)  # 49 ms after the last: the fallback, within a timer's jitter


@pytest.mark.parametrize("phase", [0.0, 0.004, 0.012, 0.018])
def test_the_at_home_combination_fires_within_hold_s_plus_50_ms(phase):
    hc = pytest.importorskip("amr_line.home_combo")

    def buttons(t):  # Reset first, Start 0.2 s later, both held 2 s
        return (1.2 <= t < 3.5, 1.0 <= t < 3.5)

    pub, _ = run(buttons, 4.0, phase_s=phase, jitter_s=0.003, seed=3)
    combo = hc.HomeCombo()
    edge_t = fired = None
    for t, f in pub:  # what line_follow_node receives
        if f.start_edge:
            edge_t = t
        if combo.tick(t, f.valid, f.mode_auto, f.start_held, f.reset_held, f.start_edge, f.reset_edge):
            assert fired is None, "one fire per hold"
            fired = t
    assert edge_t is not None and fired is not None
    assert hc.HOLD_S <= fired - edge_t <= hc.HOLD_S + 0.050, fired - edge_t


def test_the_link_edge_is_a_code_not_a_substring():
    """WP-H2: DIO_LINK_LOST / DIO_LINK_OK ride the frame; the PANEL text no longer carries the link."""
    ad = panel_io.PanelAdapter(debounce_scans=2, pendant=False)
    snap = {"comms_ok": True, "di": _di(), "detail": "ok", "rx_age_s": 0.01, "connected": True, "scans": 1}
    f = ad.tick(snap)
    assert f.link == panel_io.LINK_OK and "DIO comms ok" in f.link_text
    f = ad.tick(dict(snap, scans=2))
    assert f.link is None
    f = ad.tick(dict(snap, comms_ok=False, detail="timeout", scans=2))
    assert f.link == panel_io.LINK_LOST and "timeout" in f.link_text
    assert f.other == "panel image invalid" and f.warn
    assert "LOST" in f.changed  # the log line keeps every note


def test_panel_node_has_no_horn_engine_and_takes_the_lamp_from_drive_status():
    """WP-C7 + lean plan D16: no /cmd_wheel_vel; /drives/status only for `turning` (the 41 Hz
    /wheel_states only on a DriveStatus built before the field); the stop-call pulse stays."""
    import pathlib

    src = (pathlib.Path(panel_io.__file__).parent / "panel_node.py").read_text(encoding="utf-8")
    assert "create_subscription(WheelVelocities" not in src
    assert "horn_wanted" not in src and "HORN_DO_CHANNEL" not in src
    assert '"/drives/status", self._on_drives' in src and "m.turning" in src
    assert "panel_io.call_wanted(" in src and "panel_io.call_phase(" in src
    assert not hasattr(panel_io, "horn_wanted")
    msg = pathlib.Path(panel_io.__file__).parents[2] / "amr_interfaces" / "msg" / "DriveStatus.msg"
    fields = [ln.split() for ln in msg.read_text(encoding="utf-8").splitlines()
              if ln.strip() and not ln.lstrip().startswith("#")]
    # appended, never inserted; the bus voltages came after it (WP-P7 / emergency E5, 2026-11-16)
    assert fields[-3:] == [["bool", "turning"], ["float32", "left_bus_v"], ["float32", "right_bus_v"]]


def test_wheels_turning_is_the_old_lamp_rule():
    wt = panel_io.wheels_turning
    assert wt(True, 0.5, True, 0.0) and wt(False, 0.0, True, -0.02)
    assert not wt(True, 0.01, True, -0.01)  # at the noise floor
    assert not wt(False, 3.0, False, 3.0)  # invalid feedback is not turning
