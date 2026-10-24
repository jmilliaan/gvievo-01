"""/scan and /tf on demand (2026-10-24): live-view and demo requests mark demand, it lapses
LIVE_IDLE_S after the last one, and the scanner alarm's liveness comes from the driver's
"/scan topic status" diagnostic while nothing is subscribed."""

from amr_web.live import LIVE_IDLE_S, SCAN_DIAG_SUFFIX, LiveStore, scan_diag_progress
from amr_web.server import create_app


def test_demand_lapses_after_the_idle_time():
    st = LiveStore()
    assert not st.wanted(100.0), "nothing asked yet"
    st.want(100.0)
    assert st.wanted(100.0) and st.wanted(100.0 + LIVE_IDLE_S - 0.01)
    assert not st.wanted(100.0 + LIVE_IDLE_S)
    st.want(110.0)
    assert st.wanted(110.0 + LIVE_IDLE_S - 0.01), "a later request renews it"


def test_the_wake_up_hook_runs_only_when_demand_had_lapsed():
    st = LiveStore()
    woken = []
    st.on_want = lambda: woken.append(1)
    st.want(0.0)
    st.want(0.2)                   # a page polling at 5 Hz: one wake-up, not one per request
    st.want(4.9)
    assert len(woken) == 1
    st.want(4.9 + LIVE_IDLE_S)     # the page was closed long enough to drop the subscriptions
    assert len(woken) == 2


def test_a_failing_hook_never_fails_the_request():
    st = LiveStore()

    def boom():
        raise RuntimeError("guard condition gone (shutdown)")

    st.on_want = boom
    st.want(0.0)
    assert st.wanted(0.0), "the 1 s reconcile timer still sees the demand"


def test_dropping_the_subscriptions_forgets_the_last_sample():
    st = LiveStore()
    st.set_pose(1.0, 2.0, 0.0, "map")
    st.set_scan([(1.0, 1.0)], "map")
    st.clear_live()
    d = st.pose_scan()
    assert d["pose"] is None and d["scan"] is None


def test_scan_diag_progress_reads_the_driver_counter():
    first, alive = scan_diag_progress(None, {"Events since startup": "47230", "Events in window": "85"})
    assert (first, alive) == (47230, True)
    n, alive = scan_diag_progress(first, {"Events since startup": "47247", "Events in window": "85"})
    assert (n, alive) == (47247, True)
    n, alive = scan_diag_progress(n, {"Events since startup": "47247", "Events in window": "0"})
    assert alive is False, "a frozen counter is no evidence: the age keeps growing"
    n, alive = scan_diag_progress(n, {"Events since startup": "12", "Events in window": "12"})
    assert (n, alive) == (12, True), "a driver restart resets the counter: still a change"


def test_scan_diag_progress_without_evidence():
    assert scan_diag_progress(None, {"Events since startup": "0", "Events in window": "0"}) == (0, False)
    assert scan_diag_progress(7, {}) == (7, False), "another driver version: no evidence, keep the counter"
    assert scan_diag_progress(7, {"Events since startup": "n/a"}) == (7, False)


def test_the_diag_name_matches_the_vehicle_driver():
    assert "sick_safetyscanners2_node: /scan topic status".endswith(SCAN_DIAG_SUFFIX)


class _Live(LiveStore):
    def __init__(self):
        super().__init__()
        self.wants = 0

    def want(self, now=None):
        self.wants += 1
        super().want(now)


class _Stub:
    def __init__(self):
        self.live = _Live()

    def state(self):
        return {}

    def events(self, since=0):
        return []

    def diagnostics(self):
        return {}

    def event_log_files(self):
        return []

    def emit(self, *a, **k):
        pass


def test_live_and_demo_requests_mark_demand(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    stub = _Stub()
    app = create_app(stub, str(maps), state_dir=str(tmp_path / "state"))
    app.config["TESTING"] = True
    c = app.test_client()
    for url in ("/api/live/pose", "/api/live/map", "/api/live/map.png?snapshot=0", "/api/demo"):
        before = stub.live.wants
        c.get(url)
        assert stub.live.wants == before + 1, url
    before = stub.live.wants
    c.get("/api/state")
    assert stub.live.wants == before, "the 1 Hz state poll every page makes is not live-view demand"
