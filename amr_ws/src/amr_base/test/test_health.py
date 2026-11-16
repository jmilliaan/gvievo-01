"""agv_core.health and amr_base.health_pub (unified plan WP-H1, hardening plan H-P1-1): the
transition tables per device, the owner's outbox, the consumer view and the correlator.
Pure, no ROS. Reporting only: nothing here can move the vehicle, so a wrong state is a wrong
HMI line - these pin which line."""

from __future__ import annotations

import math
import pathlib
import re
from types import SimpleNamespace

from agv_core import alarms, config, health
from agv_core.health import ABSENT, DEGRADED, FROZEN, LOST, OK, RECONNECTING, STALE, Row

from amr_base import health_pub, wire

LATE = 60.0  # owner uptime well past the boot grace


def _codes(*rows):
    return [r.code for r in rows]


# ---------------------------------------------------------------- tables


def test_the_names_are_wire_s_tables_in_order():
    assert tuple(wire.HEALTH_DEVICE_NAMES[i] for i in range(len(wire.HEALTH_DEVICE_NAMES))) == health.DEVICES
    assert tuple(wire.HEALTH_STATE_NAMES[i] for i in range(len(wire.HEALTH_STATE_NAMES))) == health.STATES
    assert set(health.OWNER) == set(health.LOST_CODE) == set(health.DEVICES)
    assert "rfid" not in health.DEVICES and not any("bms" in d for d in health.DEVICES)  # decisions 23, 16


def test_every_code_health_can_raise_has_a_catalogue_row():
    src = pathlib.Path(health.__file__).read_text(encoding="utf-8")
    literals = set(re.findall(r'"([A-Z][A-Z0-9]*_[A-Z0-9_]+)"', src))
    codes = literals | set(health.LOST_CODE.values()) | {g.code for g in health.GROUPS}
    codes = {c for c in codes if not hasattr(config, c)}  # profile keys read by configured()
    missing = sorted(c for c in codes if c not in alarms.CATALOGUE)
    assert not missing, missing


def test_the_msg_has_the_fields_fill_writes():
    msg = (pathlib.Path(__file__).resolve().parents[2] / "amr_interfaces" / "msg" / "DeviceHealth.msg")
    msg = msg.read_text()
    lines = [ln.split("#")[0].split() for ln in msg.splitlines()]
    fields = {ln[1] for ln in lines if len(ln) == 2 and "=" not in ln[1]}
    m = health.fill(SimpleNamespace(), Row("dio", OK), health_pub.DEVICE_IDS, health_pub.STATE_IDS)
    assert set(vars(m)) | {"header"} == fields
    consts = dict(re.findall(r"^uint8 (\w+)=(\d+)", msg, re.M))
    assert {k: int(v) for k, v in consts.items() if k.startswith("DEVICE_")} == {
        f"DEVICE_{n.upper()}": i for i, n in wire.HEALTH_DEVICE_NAMES.items()}
    assert {k: int(v) for k, v in consts.items() if not k.startswith("DEVICE_")} == {
        n: i for i, n in wire.HEALTH_STATE_NAMES.items()}


def test_fill_clamps_the_counters():
    row = Row("can_bus", LOST, "CAN_BUS_LOST", "x", 1.5, 2.0, gaps=-3, rejects=2**40)
    m = health.fill(SimpleNamespace(), row, health_pub.DEVICE_IDS, health_pub.STATE_IDS)
    assert (m.device, m.state, m.code) == (2, 5, "CAN_BUS_LOST")
    assert m.gaps == 0 and m.rejects == 0xFFFFFFFF and m.age_s == 1.5 and m.since_s == 2.0


# ---------------------------------------------------------------- existence: ABSENT, never LOST


def test_an_unfitted_device_is_absent_however_long_it_is_silent():
    assert health.rear_scanner(False, LATE, "no scan", None, 0.3).state == ABSENT
    assert health.station_link(False, LATE, False, False, down_for=999.0).state == ABSENT
    assert health.dio(LATE, {"enabled": False, "rx_age_s": None}, 0.25).state == ABSENT
    assert health.mls_gyro(LATE, False, "off", None, 0.1, 1.0, False).state == ABSENT
    fitted = {d: False for d in health.DEVICES}
    lost = {d: (Row(d, LOST, health.LOST_CODE[d]), 100.0) for d in health.DEVICES}
    assert {r.state for r in health.view(lost, 100.0, fitted, LATE).values()} == {ABSENT}
    assert {r.state for r in health.view({}, 100.0, fitted, LATE).values()} == {ABSENT}


def test_the_profile_says_what_is_fitted():
    cfg = SimpleNamespace(IMU_ENABLED=True, DIO_ENABLED=True, REAR_SOURCE="none", STATION_ENABLED=False)
    f = health.configured(cfg)
    assert not f["rear_scanner"] and not f["station_link"] and f["dio"] and f["drive_left"]
    cfg.REAR_SOURCE, cfg.STATION_ENABLED = "scanner", True
    assert health.configured(cfg)["rear_scanner"] and health.configured(cfg)["station_link"]
    assert set(health.configured(config)) == set(health.DEVICES)  # the real profile loads


def test_a_fitted_device_not_seen_yet_is_absent_in_the_grace_then_lost():
    early, late = health.BOOT_GRACE_S - 1.0, health.BOOT_GRACE_S + 1.0
    assert health.drive("drive_left", 1, early, None, None, True, False, 0.1, 0.5).state == ABSENT
    r = health.drive("drive_left", 1, late, None, None, True, False, 0.1, 0.5)
    assert (r.state, r.code) == (LOST, "DRIVE_SILENT") and "never seen" in r.detail
    assert health.dio(early, {"enabled": True, "rx_age_s": None}, 0.25).state == ABSENT
    assert health.dio(late, {"enabled": True, "rx_age_s": None}, 0.25).code == "IO_ISLAND_LOST"
    assert health.rear_scanner(True, late, "no scan", None, 0.3).state == LOST


# ---------------------------------------------------------------- per device


def test_drive():
    d = lambda **k: health.drive("drive_right", 2, LATE, **{  # noqa: E731
        "alive_age": 0.01, "feedback_age": 0.01, "feedback_expected": True, "linking": False,
        "max_age": 0.05, "timeout_s": 0.3, **k})
    assert d().state == OK
    assert (d(feedback_age=0.1).state, d(feedback_age=0.1).code) == (STALE, "DRIVE_SILENT")
    assert d(feedback_age=0.5).state == LOST and "heartbeat alive" in d(feedback_age=0.5).detail
    assert d(feedback_age=None).state == LOST
    assert d(alive_age=0.5).state == LOST
    assert d(alive_age=-0.1).state == LOST  # rule 1: a negative age is not fresh
    assert d(rebooted=True).state == RECONNECTING and d(rebooted=True).code == "DRIVE_REBOOTED"
    # link down: no TPDO expected; answering heartbeats is OK, wanting the link is RECONNECTING
    assert d(feedback_expected=False, feedback_age=None).state == OK
    assert d(feedback_expected=False, feedback_age=None, linking=True).state == RECONNECTING


def test_can_bus():
    assert health.can_bus(LATE, 0.01, 0.0, 0.3).state == OK
    r = health.can_bus(LATE, 0.01, 0.1, 0.3, tx_errors=4, last_tx_error="ENOBUFS")
    assert (r.state, r.code, r.gaps) == (DEGRADED, "CAN_TX_FAILED", 4)
    assert health.can_bus(LATE, 0.01, 0.5, 0.3).state == LOST
    assert _codes(health.can_bus(LATE, 2.0, 0.0, 0.3)) == ["CAN_BUS_LOST"]
    assert health.can_bus(LATE, None, 0.0, 0.3).state == LOST


def test_mls_track():
    t = lambda **k: health.mls_track(LATE, **{  # noqa: E731
        "mode": "tpdo", "want": "auto", "age": 0.01, "stale_after": 0.05, "lost_after": 1.0,
        "probing": False, **k})
    assert t().state == OK
    assert (t(mode="sdo").state, t(mode="sdo").code) == (DEGRADED, "MLS_NO_STREAM")
    assert t(mode="sdo", want="sdo").state == OK  # polling by choice is not degraded
    assert (t(age=0.2).state, t(age=0.2).code) == (STALE, "MLS_SILENT")
    assert t(age=2.0).state == LOST
    assert t(mode="off", probing=True).state == RECONNECTING
    assert t(mode="off").state == LOST
    assert t(want="off", mode="off").state == ABSENT


def test_mls_gyro():
    g = lambda **k: health.mls_gyro(LATE, **{  # noqa: E731
        "enabled": True, "mode": "tpdo", "age": 0.01, "stale_after": 0.1, "lost_after": 1.0,
        "probing": False, **k})
    assert g().state == OK and g(mode="sdo").state == OK
    assert (g(age=0.3).state, g(age=0.3).code) == (STALE, "IMU_STALE")
    assert g(age=3.0).state == LOST
    assert g(mode="off", probing=True).state == RECONNECTING
    # MlsImu.frozen (StampTracker latch, H-P1-7): FROZEN whatever the age; not answering still wins
    assert (g(frozen=True).state, g(frozen=True).code) == (FROZEN, "IMU_STALE")
    assert g(frozen=True, age=3.0).state == FROZEN and g(frozen=True, age=None).state == FROZEN
    assert g(frozen=True, mode="off").state == LOST
    assert g(frozen=True, enabled=False).state == ABSENT


class _Reply:
    def __init__(self, bits, error=False):
        self.bits, self._error = bits, error

    def isError(self):  # noqa: N802 - pymodbus
        return self._error


class _Modbus:
    """Answers bit reads; fails the next `fail` reads."""

    def __init__(self):
        self.fail = 0

    def connect(self):
        return True

    def _bits(self, address, count, device_id=1):
        if self.fail:
            self.fail -= 1
            return _Reply([], error=True)
        return _Reply([False] * count)

    read_discrete_inputs = read_coils = _bits

    def write_coil(self, address, value, device_id=1):
        return _Reply([value])

    def close(self):
        pass


def test_dio_from_the_real_snapshot_and_the_retry_feeds_degraded():
    """DioLink.snapshot()'s keys as dio.py writes them, not as this test imagines them."""
    from agv_core.drivers import dio as dio_mod

    was = config.DIO_ENABLED
    config.DIO_ENABLED = True
    try:
        fake = _Modbus()
        link = dio_mod.DioLink(client_factory=lambda: fake)
        limit = config.PANEL_SOURCE_MAX_AGE_S
        link._scan_with_retry()
        assert health.dio(LATE, link.snapshot(), limit).state == OK
        fake.fail = 1  # one bad reply, saved by the immediate retry: no stop, but DEGRADED
        link._scan_with_retry()
        r = health.dio(LATE, link.snapshot(), limit)
        assert (r.state, r.code, r.gaps) == (DEGRADED, "DIO_SCAN_RETRIED", 1)
        link._drop("cable")
        r = health.dio(LATE, link.snapshot(), limit)
        assert (r.state, r.code) == (LOST, "IO_ISLAND_LOST")
    finally:
        config.DIO_ENABLED = was
    stale = {"enabled": True, "connected": True, "comms_ok": True, "rx_age_s": limit + 0.1}
    assert health.dio(LATE, stale, limit).state == STALE


def test_rear_scanner_from_trolley_detect():
    from amr_base import trolley_detect as td

    p = td.Params(roi_x_min_m=0.1, roi_x_max_m=1.2, roi_half_width_m=0.4, present_points=20, absent_points=5,
                  present_s=0.5, absent_s=1.0, stale_s=0.3, max_invalid_ratio=0.5)
    d = td.TrolleyDetect(p)
    d.tick(LATE)
    assert health_pub.rear_row(LATE, LATE, d, True).state == LOST  # "no scan", never seen
    ranges = [math.inf] * 721
    d.scan(LATE, ranges, -math.pi / 2, math.pi / 720, 0.05, 40.0, counter=1)
    d.tick(LATE)
    assert health_pub.rear_row(LATE, LATE, d, True).state == OK  # scans arrive; the debounce runs
    d.scan(LATE, [float("nan")] * 721, -math.pi / 2, math.pi / 720, 0.05, 40.0, counter=2)
    assert health_pub.rear_row(LATE, LATE, d, True).state == DEGRADED  # arriving, not usable
    d.scan(LATE, ranges, -math.pi / 2, math.pi / 720, 0.05, 40.0, counter=1)
    d.tick(LATE + 1.0)  # stale
    r = health_pub.rear_row(LATE + 1.0, LATE, d, True)
    assert (r.state, r.code) == (LOST, "REAR_SCANNER_SILENT")
    d.scan(LATE + 1.1, ranges, -math.pi / 2, math.pi / 720, 0.05, 40.0, counter=1)
    d.scan(LATE + 1.5, ranges, -math.pi / 2, math.pi / 720, 0.05, 40.0, counter=1)  # same content > stale_s
    assert health_pub.rear_row(LATE + 1.5, LATE, d, True).state == FROZEN
    assert health_pub.rear_row(LATE + 1.5, LATE, d, False).state == ABSENT


def test_station_link():
    s = lambda **k: health.station_link(True, LATE, **{"connected": True, "ready": True, **k})  # noqa: E731
    assert s().state == OK
    assert s(ready=False).state == RECONNECTING
    r = s(connected=False, ready=False, down_for=30.0)
    assert (r.state, r.code) == (LOST, "STATION_LINK_DOWN") and "30 s" in r.detail
    assert health.station_link(True, 1.0, False, False).state == RECONNECTING  # still connecting at boot
    assert health.station_link(True, 1.0, False, False, failed="bad mode 644").state == LOST


# ---------------------------------------------------------------- drive_node's adapters


def test_drive_rows_read_the_drive_link():
    from amr_base import canopen

    now = 100.0
    tel = {1: canopen.DriveTelemetry(t_status=now - 0.01, t_position=now - 0.02, t_alive=now - 0.01),
           2: canopen.DriveTelemetry(t_alive=now - 1.0)}
    link = SimpleNamespace(state=canopen.ARMED, telemetry=tel, rebooted_nodes=lambda: [],
                           router=SimpleNamespace(error_frames=3))
    left, right = health_pub.drive_rows(now, LATE, link, (1, 2), True, 0.05, 0.3)
    assert (left.device, left.state) == ("drive_left", OK)
    assert (right.device, right.state, right.code) == ("drive_right", LOST, "DRIVE_SILENT")
    bus = health_pub.bus_row(now, LATE, link, canopen.TxHealth(), 0.3, sdo_timeouts=7)
    assert (bus.state, bus.rejects, bus.timeouts) == (OK, 3, 7)
    link.state = canopen.DISARMED
    assert health_pub.drive_rows(now, LATE, link, (1, 2), True, 0.05, 0.3)[0].state == RECONNECTING


def test_track_and_gyro_rows_read_the_mls_readers():
    track = SimpleNamespace(mode="sdo", want="auto", stale_after=lambda: 0.3, age=lambda now: 0.05,
                            _chain=None, _rediscover_at=None, stale_periods=2, restarts=1, misses=4)
    r = health_pub.track_row(10.0, LATE, track)
    assert (r.state, r.code, r.gaps, r.reconnects, r.timeouts) == (DEGRADED, "MLS_NO_STREAM", 2, 1, 4)
    assert health_pub.track_row(10.0, LATE, None).state == LOST
    imu = SimpleNamespace(mode="off", poll_period=0.02, _chain=object(), _rediscover_at=None,
                          rejected=0, restarts=0, misses=0)
    assert health_pub.gyro_row(10.0, LATE, imu, True, None).state == RECONNECTING
    assert health_pub.gyro_row(10.0, LATE, None, False, None).state == ABSENT


# ---------------------------------------------------------------- the outbox


def test_the_book_sends_edges_at_once_and_repeats_at_2_hz():
    b = health.Book()
    ok, lost = Row("dio", OK), Row("dio", LOST, "IO_ISLAND_LOST")
    assert b.offer(0.0, ok) is not None
    assert b.offer(0.1, ok) is None and b.offer(0.4, ok) is None
    again = b.offer(0.5, ok)
    assert again is not None and math.isclose(again.since_s, 0.5)
    assert b.edge(lost) and not b.edge(ok)
    sent = b.offer(0.6, lost)  # an edge goes at once, inside the period
    assert sent is not None and sent.since_s == 0.0
    assert b.offer(0.7, Row("dio", LOST, "IO_ISLAND_LOST", "other detail")) is None  # detail is not an edge
    assert b.offer(0.6, Row("drive_left", OK)) is not None  # per device


class _Node:
    def __init__(self):
        self.logged = []

    def get_logger(self):
        return SimpleNamespace(warn=self.logged.append, error=self.logged.append)


def test_the_outbox_runs_without_the_msg_and_never_raises():
    node = _Node()
    box = health_pub.Outbox(node)  # no amr_interfaces here: decides, publishes nothing
    assert box._pub is None and node.logged
    sent = box.publish(0.0, [Row("dio", OK), Row("can_bus", OK)])
    assert [r.device for r in sent] == ["dio", "can_bus"]
    assert box.publish(0.1, [Row("dio", OK)]) == []
    box._pub, box._msg = object(), SimpleNamespace  # a publish path that fails
    box.publish(5.0, [Row("not_a_device", OK)])  # fill() raises KeyError: counted, not raised
    assert box.errors == 1 and "KeyError" in node.logged[-1]


# ---------------------------------------------------------------- the consumer


def test_the_view_shows_a_silent_owner_as_lost():
    fitted = {d: True for d in health.DEVICES}
    rows = {"dio": (Row("dio", OK, since_s=3.0), 99.5), "can_bus": (Row("can_bus", OK), 90.0)}
    v = health.view(rows, 100.0, fitted, LATE)
    assert v["dio"].state == OK and math.isclose(v["dio"].since_s, 3.5)
    assert (v["can_bus"].state, v["can_bus"].code) == (LOST, "CAN_BUS_LOST")
    assert "drive_node" in v["can_bus"].detail
    assert (v["station_link"].state, v["station_link"].code) == (LOST, "STATION_LINK_DOWN")
    assert health.view({}, 100.0, fitted, 1.0)["dio"].state == ABSENT  # just started listening


def _all_ok(**down):
    rows = {d: Row(d, OK) for d in health.DEVICES}
    rows.update(down)
    return rows


def test_one_cable_is_one_line():
    rows = _all_ok(
        drive_left=Row("drive_left", LOST, "DRIVE_SILENT", since_s=2.0),
        drive_right=Row("drive_right", LOST, "DRIVE_SILENT", since_s=2.3),
        mls_track=Row("mls_track", STALE, "MLS_SILENT", since_s=2.1),
        mls_gyro=Row("mls_gyro", LOST, "IMU_STALE", since_s=2.2),
        can_bus=Row("can_bus", LOST, "CAN_BUS_LOST", since_s=2.0),
        station_link=Row("station_link", LOST, "STATION_LINK_DOWN", since_s=2.0),
    )
    found, taken = health.classify(rows)
    assert [f.code for f in found] == ["CAN_BUS_LOST"]
    assert taken == {"drive_left", "drive_right", "mls_track", "can_bus", "mls_gyro"}
    # station_link is Wi-Fi, not the shared cable: never folded in
    assert [f.code for f in health.standing(rows)] == ["CAN_BUS_LOST", "STATION_LINK_DOWN"]


def test_losses_far_apart_are_separate_causes():
    rows = _all_ok(
        drive_left=Row("drive_left", LOST, "DRIVE_SILENT", since_s=2.0),
        drive_right=Row("drive_right", LOST, "DRIVE_SILENT", since_s=2.0),
        mls_track=Row("mls_track", LOST, "MLS_SILENT", since_s=3600.0),
    )
    assert health.classify(rows)[0] == []
    assert sorted(f.code for f in health.standing(rows)) == ["DRIVE_SILENT", "DRIVE_SILENT", "MLS_SILENT"]


def test_track_and_gyro_together_are_the_sensor():
    rows = _all_ok(mls_track=Row("mls_track", LOST, "MLS_SILENT", since_s=1.0),
                   mls_gyro=Row("mls_gyro", RECONNECTING, "IMU_STALE", since_s=1.4))
    assert [f.code for f in health.standing(rows)] == ["MLS_OFFLINE"]


def test_the_io_island_is_the_dio_alone():
    rows = _all_ok(dio=Row("dio", LOST, "IO_ISLAND_LOST", "no scan", since_s=0.5))
    assert [(f.code, f.devices) for f in health.standing(rows)] == [("IO_ISLAND_LOST", ("dio",))]
    flaky = _all_ok(dio=Row("dio", DEGRADED, "DIO_SCAN_RETRIED"))
    assert health.standing(flaky)[0].code == "DIO_SCAN_RETRIED"
    assert health.standing(_all_ok()) == []
