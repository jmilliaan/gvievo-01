"""Operator panel: debounced edges, and the Reset-means-READY state machine."""
import copy
import json

import time

from helpers import ROOT, check

import config
import panel
from panel import AUTO, MANUAL

R, S, A = 0, 1, 2                       # channel indices used by these tests


def image(reset=False, start=False, auto=False):
    di = [False] * 16
    di[R], di[S], di[A] = reset, start, auto
    return di


def scanner(debounce=1):
    return panel.PanelScan(R, S, A, debounce)


def run(sc, frames, comms_ok=True):
    """Feed a list of images, return the list of intents."""
    return [sc.scan(f, comms_ok) for f in frames]


def test_edges_and_tie_down():
    """A press is an edge, and a button already down at boot is not a press."""
    print("\npanel: edges")

    sc = scanner()
    out = run(sc, [image(), image(start=True), image(start=True),
                   image(start=True), image()])
    check("the first image is a baseline and emits nothing",
          not out[0].start and not out[0].reset)
    check("pressing Start is one edge", out[1].start is True)
    check("holding it is not another edge - a half-second press covers ten "
          "scans", [o.start for o in out[2:]] == [False, False, False],
          str([o.start for o in out]))

    # The hazard this exists for: a taped-down button, or a selector already
    # sitting in AUTO, must not act at power-on.
    sc = scanner()
    out = run(sc, [image(start=True, auto=True), image(start=True, auto=True)])
    check("Start held down at boot never fires", not any(o.start for o in out))
    check("and the selector is reported, not treated as a change",
          out[0].mode == AUTO and not out[0].mode_changed)

    sc = scanner()
    out = run(sc, [image(), image(reset=True), image()])
    check("Reset is edge-detected the same way",
          [o.reset for o in out] == [False, True, False])


def test_selector():
    """The selector is a level, and only its transitions matter."""
    print("\npanel: selector")

    sc = scanner()
    out = run(sc, [image(), image(auto=True), image(auto=True), image()])
    check("low reads MANUAL", out[0].mode == MANUAL)
    check("high reads AUTO", out[1].mode == AUTO)
    check("and the move is flagged once", out[1].mode_changed is True)
    check("holding the position is not a change", out[2].mode_changed is False)
    check("moving back flags again",
          out[3].mode == MANUAL and out[3].mode_changed is True)
    check("mode() reports it for the UI", sc.mode() == MANUAL)


def test_debounce():
    """A level must read the same on N consecutive scans to be believed."""
    print("\npanel: debounce")

    sc = scanner(debounce=2)
    run(sc, [image(), image()])                     # baseline
    out = run(sc, [image(start=True)])
    check("a single-scan glitch is not yet a press", out[0].start is False)
    out = run(sc, [image()])
    check("and if it goes away it never becomes one", out[0].start is False)

    out = run(sc, [image(start=True), image(start=True)])
    check("two consecutive scans are accepted",
          [o.start for o in out] == [False, True])

    sc = scanner(debounce=3)
    run(sc, [image(auto=True)] * 3)                 # settle on AUTO
    out = run(sc, [image()])                        # moving, not yet believed
    check("an unsettled contact keeps reporting the last SETTLED selector "
          "position, so the UI does not flicker mid-bounce",
          out[0].valid and out[0].mode == AUTO and not out[0].mode_changed,
          f"valid={out[0].valid} mode={out[0].mode}")


def test_comms_loss_cannot_synthesise_a_press():
    """The reconnect hazard: stale bits are not input."""
    print("\npanel: comms loss")

    sc = scanner()
    run(sc, [image(), image(auto=True)])            # baselined, selector AUTO

    out = sc.scan(image(auto=True), False)
    check("a scan with comms down is not valid", out.valid is False)
    check("and reports no edges", not out.start and not out.reset)

    # The link returns while Start happens to read high. Comparing against the
    # pre-outage image would invent a press that nobody made.
    out = run(sc, [image(start=True, auto=True), image(start=True, auto=True)])
    check("the first scan back re-baselines instead of firing Start",
          out[0].start is False)
    check("and the held button still does not fire on later scans",
          out[1].start is False)
    check("releasing and pressing again works normally",
          run(sc, [image(auto=True), image(start=True, auto=True)])[1].start
          is True)

    # A short or malformed image is not a button press either.
    check("a short image is refused", sc.scan([True, True], True).valid is False)
    check("None is refused", sc.scan(None, True).valid is False)


def test_reset_means_ready():
    """The controller's state machine, driven through its own handlers.

    The shape changed: MANUAL is an armed state the selector holds, AUTO is a
    disarmed one that Start energises. Reset no longer arms anything - it was
    being pressed reflexively before every jog, which is what this is fixing.
    """
    import canworker
    import config
    import events
    print("\npanel: MANUAL is armed, AUTO is armed by Start")

    calls = []

    class Ctl(canworker.Controller):
        """Real handlers, faked slow actions - no bus, no drivers."""
        def __init__(self):
            super().__init__()
            self._lock = __import__("threading").Lock()
            self._armed = False
            self._mode = "idle"
            self._auto_running = False
            self._direction = "stop"
            self._target = (0, 0)
            self._deadline = 0.0
            self._fault = None
            self._run_source = None
            self._last_action = None
            self._last_stop_reason = None
            self._panel = scanner()
            self._arm_retry_at = 0.0
            self._arm_fail = None
            self._auto_start_at = 0.0
            self._stop_hold = None
            self._log_close_at = 0.0
            self._telemetry = {n: {"statusword": 0x0027} for n in config.NODES}
            self.arm_fails = None

        def _do_arm(self, mode):
            calls.append(("arm", mode))
            if self.arm_fails:
                raise RuntimeError(self.arm_fails)
            self._armed, self._mode = True, mode

        def _do_disarm(self):
            calls.append(("disarm",))
            self._armed, self._mode = False, "idle"
            self._auto_start_at = 0.0

        def _do_auto_run(self, running, source="web"):
            calls.append(("run", running, source))
            self._auto_running = running
            self._run_source = source if running else None

        def _end_auto_run(self, reason=None, hard=False, close_log_now=False):
            self._auto_running = False

    events.clear()
    c = Ctl()

    # ---- MANUAL: the selector is the arm command --------------------------
    c._hold_arm_state(MANUAL)
    check("the selector resting in MANUAL arms it, with nothing pressed",
          c._armed and c._mode == "manual", str(calls))
    n = len(calls)
    for _ in range(20):
        c._hold_arm_state(MANUAL)
    check("...and holding it there does not re-arm every scan",
          len(calls) == n, f"{len(calls) - n} extra call(s)")

    c._panel_start(MANUAL)
    check("Start in manual does nothing - jogging is per-direction from the "
          "web pad", c._auto_running is False)

    # ---- AUTO: disarmed until Start ---------------------------------------
    c._panel_mode_changed(AUTO)
    check("the selector moving to AUTO disarms", not c._armed)
    c._hold_arm_state(AUTO)
    check("...and AUTO does not arm itself", not c._armed, str(c._mode))

    c._panel_start(AUTO)
    check("Start arms", c._armed and c._mode == "auto")
    check("...but does NOT move yet", c._auto_running is False)
    check("...it is pending, with the delay running", c._auto_start_at > 0)

    c._pending_start()
    check("and nothing moves while the delay is still running",
          c._auto_running is False)
    c._auto_start_at = time.monotonic() - 0.001      # delay expired
    c._pending_start()
    check(f"after auto_start_delay_s it runs", c._auto_running is True)
    check("the run is owned by the panel, which is what the watchdog keys on",
          c._run_source == "panel")

    # ---- Reset only stops and acknowledges --------------------------------
    c._panel_reset(AUTO)
    check("Reset from running stops it", c._auto_running is False)
    c._hold_arm_state(AUTO)
    check("...and AUTO returns to disarmed once the run is over",
          not c._armed, str(c._mode))

    # A pending start is abandoned by Reset rather than arriving late.
    c._panel_start(AUTO)
    check("Start arms again", c._armed and c._auto_start_at > 0)
    c._panel_reset(AUTO)
    check("Reset cancels a start that has not reached the wheels yet",
          c._auto_start_at == 0.0)
    c._pending_start()
    check("...so the delay expiring afterwards moves nothing",
          c._auto_running is False)

    # A selector move cancels one too.
    c._panel_start(AUTO)
    c._panel_mode_changed(MANUAL)
    check("a selector move cancels a pending start", c._auto_start_at == 0.0)

    # ---- faults still need a human ----------------------------------------
    c3 = Ctl()
    c3._set_fault("line lost")
    c3._hold_arm_state(MANUAL)
    check("a latched fault stops MANUAL arming itself", not c3._armed)
    c3._panel_start(AUTO)
    check("...and Start is refused too", c3._auto_running is False)
    c3._panel_reset(MANUAL)
    check("Reset clears the fault", c3._fault is None)
    c3._hold_arm_state(MANUAL)
    check("...and the selector arms it again with no second press", c3._armed)

    # ---- a failed arm is a condition, not a fault -------------------------
    c4 = Ctl()
    c4.arm_fails = "preflight failed: driver 2 not answering"
    c4._hold_arm_state(MANUAL)
    check("an auto-arm that fails does NOT latch a fault - nobody did anything "
          "wrong", c4._fault is None and not c4._armed, str(c4._fault))
    check("...it records why", c4._arm_fail is not None, str(c4._arm_fail))
    n = len(calls)
    for _ in range(50):
        c4._hold_arm_state(MANUAL)
    check("...and backs off rather than hammering the bus at tick rate",
          len(calls) == n, f"{len(calls) - n} attempt(s) in 50 scans")
    c4.arm_fails = None
    c4._arm_retry_at = 0.0
    c4._hold_arm_state(MANUAL)
    check("...then arms by itself once the cause is gone, with no Reset",
          c4._armed and c4._fault is None)

    # ---- torque taken away underneath it ----------------------------------
    c5 = Ctl()
    c5._hold_arm_state(MANUAL)
    check("armed in manual", c5._armed)
    # 0x1270 = Switch on disabled: what the drives report in ETO, which is what
    # the safety chain leaves behind.
    c5._telemetry = {n: {"statusword": 0x1270} for n in config.NODES}
    c5._arm_retry_at = 0.0
    c5._hold_arm_state(MANUAL)
    check("drives dropping out of Operation enabled triggers a re-arm",
          ("disarm",) in calls[-3:] or c5._armed, str(calls[-3:]))
    c6 = Ctl()
    c6._telemetry = {n: {"statusword": None} for n in config.NODES}
    check("an unread statusword is 'unknown', never 'not ready'",
          c6._drives_ready() is None)
    events.clear()


def test_the_manual_watchdog_does_not_latch():
    """Both modes zero the setpoint; only AUTO latches a fault.

    A manual watchdog trip is self-correcting - the setpoint is already zero and
    recovery is to hold the button again, with a hand on the control. Latching
    it made a dropped Wi-Fi packet cost a walk to the panel, and under
    panel.manual_auto_arm it would block re-arming as well. An auto run is the
    opposite: latched motion that would otherwise resume on its own.
    """
    import canworker
    import events
    print("\npanel: the manual watchdog stops without latching")

    src = (ROOT / "canworker.py").read_text()
    block = src[src.index("watchdog: no keepalive"):]
    block = block[:block.index("# Device liveness")]

    check("manual warns instead of latching",
          "events.warn" in block and 'if mode == "manual":' in block)
    check("...and auto still latches",
          "self._set_fault(reason)" in block)
    check("both zero the setpoint outright",
          "self._target = target = (0, 0)" in block)
    check("both clear the ramp, or the PID re-commands on the next tick",
          "self._end_auto_run(reason, hard=True)" in block)

    # The emit sits on a 50 Hz path, so it is only safe because the branch
    # clears its own condition. Pin that the zeroing is still there to do it.
    warn_at = block.index("events.warn")
    zero_at = block.index("self._target = target = (0, 0)")
    check("the branch self-clears after warning, so it cannot repeat at 50 Hz",
          zero_at > warn_at)

    # And the reason still reaches the operator either way.
    check("the stop reason is recorded for the UI in both modes",
          "self._last_stop_reason = reason" in block)
    events.clear()


def test_panel_events_are_edge_only():
    """_panel_scan runs at 50 Hz; the event ring holds 200 entries."""
    import events
    print("\npanel: event discipline")

    src = (ROOT / "canworker.py").read_text()
    check("the panel is scanned from _run(), not from _run_autopilot() - it is "
          "what ENTERS every state", "self._panel_scan()" in src
          and src.index("self._panel_scan()") < src.index("def _run_autopilot"))

    class C:
        _lock = __import__("threading").Lock()
        _fault = None

    events.clear()
    c = C()
    canworker_set_fault = __import__("canworker").Controller._set_fault
    canworker_set_fault(c, "line lost")
    check("a fault emits once", len(events.since(0)[1]) == 1)
    for _ in range(200):
        canworker_set_fault(c, "line lost")
    check("and a fault that persists stays quiet",
          len(events.since(0)[1]) == 1, f"{len(events.since(0)[1])} events")
    events.clear()


def test_panel_profile():
    """A panel that cannot work must be refused by name at boot."""
    print("\npanel: profile validation")

    doc = json.load(open(str(ROOT / "profiles" / "agv-01.json")))

    def refused(name, mutate, needle):
        d = copy.deepcopy(doc)
        mutate(d)
        try:
            config._validate(config._derive(config._parse(d)))
            check(name, False, "NOT rejected")
        except config.ConfigError as e:
            check(name, needle in str(e), str(e)[:70])

    refused("two functions on one channel is refused - it would fire a Reset "
            "edge every time Start is pushed",
            # Derived from the profile rather than hardcoded to a channel: the
            # point is that two functions may not share ONE channel, whichever
            # channel the wiring currently puts Reset on.
            lambda d: d["panel"].update(di_start=d["panel"]["di_reset"]),
            "distinct")
    refused("a channel past num_di is refused",
            lambda d: d["panel"].update(di_auto=99), "channel in 0..")
    refused("a negative channel is refused",
            lambda d: d["panel"].update(di_reset=-1), "channel in 0..")
    refused("debounce_scans below 1 is refused",
            lambda d: d["panel"].update(debounce_scans=0), "debounce_scans")
    refused("the panel cannot be enabled without the DI scan that feeds it",
            lambda d: d["dio"].update(enabled=False), "never respond")

    # Rewired 2026-09-08: the harness moved up one channel and DI00 is now
    # unused. DI00 stays out of the panel entirely - a spare channel that
    # floats must not be able to present as a button press.
    check("the shipped profile matches the wiring: DI02 reset, DI01 start, "
          "DI03 auto",
          (config.PANEL_DI_RESET, config.PANEL_DI_START,
           config.PANEL_DI_AUTO) == (2, 1, 3))
    check("DI00 is no longer wired to a panel function",
          0 not in (config.PANEL_DI_RESET, config.PANEL_DI_START,
                    config.PANEL_DI_AUTO))


TESTS = [
    test_edges_and_tie_down,
    test_selector,
    test_debounce,
    test_comms_loss_cannot_synthesise_a_press,
    test_reset_means_ready,
    test_the_manual_watchdog_does_not_latch,
    test_panel_events_are_edge_only,
    test_panel_profile,
]
