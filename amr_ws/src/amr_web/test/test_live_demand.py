"""/scan and /tf on demand (2026-10-24): live-view requests mark demand, it lapses
LIVE_IDLE_S after the last one, and the scanner alarm's liveness comes from the driver's
"/scan topic status" diagnostic while nothing is subscribed."""

import struct

from amr_web.live import (
    DISPLAY_FRESH_S,
    DISPLAY_GRACE_S,
    DISPLAY_POSE_TOPIC,
    DISPLAY_SCAN_TOPIC,
    LIVE_IDLE_S,
    MAX_POINTS,
    SCAN_DIAG_SUFFIX,
    LiveStore,
    cloud_xy,
    live_sources,
    scan_diag_progress,
    scan_points,
)
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
    # 2026-11-16 (WP-C12): the reconcile timer is stopped while nothing is subscribed, so the
    # demand is forgotten and the next request wakes the adapter again
    assert not st.wanted(0.0)
    woken = []
    st.on_want = lambda: woken.append(1)
    st.want(0.2)
    assert woken == [1] and st.wanted(0.2)


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


def test_live_requests_mark_demand(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    stub = _Stub()
    app = create_app(stub, str(maps), state_dir=str(tmp_path / "state"))
    app.config["TESTING"] = True
    c = app.test_client()
    for url in ("/api/live/pose", "/api/live/map", "/api/live/map.png?snapshot=0"):
        before = stub.live.wants
        c.get(url)
        assert stub.live.wants == before + 1, url
    before = stub.live.wants
    c.get("/api/state")
    assert stub.live.wants == before, "the 1 Hz state poll every page makes is not live-view demand"


# ---- WP-C12 / C16 (2026-11-16) ----------------------------------------------------------


def test_scan_decimation_rounds_up_so_the_cap_holds():
    """C#20: floor division drew 576 of 1152 beams against MAX_POINTS 400."""
    for n in (1152, 401, 400, 399, 1):
        pts = scan_points([1.0] * n, 0.0, 0.001, 0.1, 10.0, 0.0, 0.0, 0.0)
        assert len(pts) <= MAX_POINTS, n
    assert len(scan_points([1.0] * 1152, 0.0, 0.001, 0.1, 10.0, 0.0, 0.0, 0.0)) == 384
    assert len(scan_points([1.0] * 400, 0.0, 0.001, 0.1, 10.0, 0.0, 0.0, 0.0)) == 400


def test_live_sources_prefer_a_fresh_display_topic_and_fall_back_to_raw():
    assert live_sources(False, 1, 0.1, 10.0) == (False, False), "nobody watching: nothing subscribed"
    assert live_sources(True, 0, None, 0.0) == (False, True), "no display publisher: today's /scan + /tf"
    assert live_sources(True, 1, None, 0.0) == (True, False), "just subscribed: give it the grace"
    assert live_sources(True, 1, None, DISPLAY_GRACE_S) == (True, True), "never published: fall back"
    assert live_sources(True, 1, DISPLAY_FRESH_S, 30.0) == (True, False)
    assert live_sources(True, 1, DISPLAY_FRESH_S + 0.1, 30.0) == (True, True), \
        "stale display: raw covers it, the display stays subscribed to switch back"


def _cloud(points, step=12, big=False, fields=(("x", 0, 7), ("y", 4, 7), ("z", 8, 7))):
    fmt = (">" if big else "<") + "fff" + "x" * (step - 12)
    return fields, step, b"".join(struct.pack(fmt, x, y, 0.0) for x, y in points)


def test_cloud_xy_reads_float32_x_y_and_drops_non_finite_points():
    f, step, data = _cloud([(1.0, 2.0), (float("nan"), 1.0), (-3.25, 0.5)])
    assert cloud_xy(f, step, data) == [(1.0, 2.0), (-3.25, 0.5)]
    f, step, data = _cloud([(1.0, 2.0)], step=16, big=True)
    assert cloud_xy(f, step, data, is_bigendian=True) == [(1.0, 2.0)], "padding, byte order from the msg"
    f, step, data = _cloud([(float(i), 0.0) for i in range(1000)])
    assert len(cloud_xy(f, step, data)) <= MAX_POINTS
    assert cloud_xy((("x", 0, 7),), 12, data) == [], "no y field: draw nothing rather than something wrong"
    assert cloud_xy((("x", 0, 8), ("y", 8, 8)), 16, b"\0" * 32) == [], "float64 is not the agreed layout"
    assert cloud_xy(f, step, b"") == []


class _Timer:
    def __init__(self):
        self.canceled = True

    def is_canceled(self):
        return self.canceled

    def cancel(self):
        self.canceled = True

    def reset(self):
        self.canceled = False


class _Log:
    def info(self, *a):
        pass


def _bare_adapter(pubs):
    """A RosAdapter without __init__: the live-view subscriptions, timers and graph faked."""
    import pytest  # noqa: PLC0415

    pytest.importorskip("rclpy")  # the vehicle (or any ROS box): adapter.py imports rclpy
    import time  # noqa: PLC0415

    from amr_web import adapter as ad  # noqa: PLC0415

    a = ad.RosAdapter.__new__(ad.RosAdapter)
    a.live = LiveStore()
    a._live_subs = a._display_subs = a._display_t = None
    a._display_since, a._live_group = 0.0, None
    a._live_tick, a._live_pose_tick = _Timer(), _Timer()
    a.subs = []
    a.create_subscription = lambda typ, topic, cb, qos, callback_group=None: a.subs.append(topic) or topic
    a.destroy_subscription = a.subs.remove
    a.count_publishers = lambda topic: pubs[0]
    a.get_logger = _Log
    return a, time.monotonic


def test_the_live_timers_and_subscriptions_run_only_while_a_page_watches():
    """WP-C12: no 5 Hz pose tick and no 1 Hz reconcile while nothing watches; WP-C16: the
    display topics when a node publishes them, else today's /tf + /scan."""
    pubs = [0]
    a, now = _bare_adapter(pubs)
    a._live_reconcile()
    assert a.subs == [] and a._live_tick.canceled and a._live_pose_tick.canceled
    a.live.want(now())
    a._live_reconcile()
    assert sorted(a.subs) == ["/scan", "/tf"], "no display publisher: the raw path"
    assert not a._live_tick.canceled and not a._live_pose_tick.canceled
    a.live.want_t = now() - LIVE_IDLE_S - 1.0  # the page closed
    a._live_reconcile()
    assert a.subs == [] and a._live_tick.canceled and a._live_pose_tick.canceled
    assert a.live.pose_scan()["pose"] is None
    pubs[0] = 1
    a.live.want(now())
    a._live_reconcile()
    assert sorted(a.subs) == sorted([DISPLAY_POSE_TOPIC, DISPLAY_SCAN_TOPIC]), "display only"
    assert not a._live_tick.canceled and a._live_pose_tick.canceled, "no TF to read: no pose tick"
    a._display_t = now() - DISPLAY_FRESH_S - 1.0  # the display publisher went quiet
    a._live_reconcile()
    assert sorted(a.subs) == sorted([DISPLAY_POSE_TOPIC, DISPLAY_SCAN_TOPIC, "/scan", "/tf"])
    assert not a._live_pose_tick.canceled
    a._display_t = now()  # it resumed
    a._live_reconcile()
    assert sorted(a.subs) == sorted([DISPLAY_POSE_TOPIC, DISPLAY_SCAN_TOPIC]) and a._live_pose_tick.canceled
