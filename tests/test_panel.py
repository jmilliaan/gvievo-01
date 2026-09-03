"""Operator panel: debounced edges, and the Reset-means-READY state machine."""
import copy
import json

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
    """The controller's state machine, driven through its own handlers."""
    import canworker
    import events
    print("\npanel: Reset means READY")

    calls = []

    class Ctl(canworker.Controller):
        """Real handlers, faked slow actions - no bus, no drivers."""
        def __init__(self):
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
            self.arm_fails = None

        def _do_arm(self, mode):
            calls.append(("arm", mode))
            if self.arm_fails:
                raise RuntimeError(self.arm_fails)
            self._armed, self._mode = True, mode

        def _do_disarm(self):
            calls.append(("disarm",))
            self._armed, self._mode = False, "idle"

        def _do_auto_run(self, running, source="web"):
            calls.append(("run", running, source))
            self._auto_running = running
            self._run_source = source if running else None

        def _end_auto_run(self, reason=None, hard=False, close_log_now=False):
            self._auto_running = False

    events.clear()
    c = Ctl()

    # IDLE -> Reset -> READY
    c._panel_reset(AUTO)
    check("Reset from idle arms in the selected mode",
          c._armed and c._mode == "auto", str(calls))

    # READY -> Start -> RUNNING
    c._panel_start(AUTO)
    check("Start runs it", c._auto_running is True)
    check("and the run is owned by the panel, which is what the watchdog "
          "keys on", c._run_source == "panel")

    # RUNNING -> Reset -> READY (stopped, still armed)
    c._panel_reset(AUTO)
    check("Reset from running stops it", c._auto_running is False)
    check("but leaves it ARMED, so Start goes again without a second Reset",
          c._armed is True)
    c._panel_start(AUTO)
    check("Start restarts it", c._auto_running is True)

    # FAULT -> Start refused -> Reset -> READY
    c._set_fault("line lost")
    c._end_auto_run()
    c._panel_start(AUTO)
    check("Start is refused while a fault is latched", c._auto_running is False)
    c._panel_reset(AUTO)
    check("Reset clears the fault", c._fault is None)
    c._panel_start(AUTO)
    check("and Start works again", c._auto_running is True)

    # Selector out of AUTO stops AND disarms
    c._panel_mode_changed(MANUAL)
    check("the selector stops the run", c._auto_running is False)
    check("and disarms, because mode is fixed at arm time",
          c._armed is False and c._mode == "idle")

    # Start in manual is a no-op
    c._panel_reset(MANUAL)
    check("Reset arms in manual", c._armed and c._mode == "manual")
    c._panel_start(MANUAL)
    check("Start in manual does nothing - jogging is per-direction from the "
          "web pad", c._auto_running is False)

    # A failed arm latches, rather than vanishing the way a 409 would
    c2 = Ctl()
    c2.arm_fails = "preflight failed: driver 2 not answering"
    c2._panel_reset(AUTO)
    check("an arm that raises latches a fault - the panel has no 409",
          c2._fault is not None and not c2._armed, str(c2._fault))
    c2.arm_fails = None
    c2._panel_reset(AUTO)
    check("and Reset retries it once the cause is gone",
          c2._armed and c2._fault is None)
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
            lambda d: d["panel"].update(di_start=0), "distinct")
    refused("a channel past num_di is refused",
            lambda d: d["panel"].update(di_auto=99), "channel in 0..")
    refused("a negative channel is refused",
            lambda d: d["panel"].update(di_reset=-1), "channel in 0..")
    refused("debounce_scans below 1 is refused",
            lambda d: d["panel"].update(debounce_scans=0), "debounce_scans")
    refused("the panel cannot be enabled without the DI scan that feeds it",
            lambda d: d["dio"].update(enabled=False), "never respond")

    check("the shipped profile matches the wiring: DI00 reset, DI01 start, "
          "DI02 auto",
          (config.PANEL_DI_RESET, config.PANEL_DI_START,
           config.PANEL_DI_AUTO) == (0, 1, 2))


TESTS = [
    test_edges_and_tie_down,
    test_selector,
    test_debounce,
    test_comms_loss_cannot_synthesise_a_press,
    test_reset_means_ready,
    test_panel_events_are_edge_only,
    test_panel_profile,
]
