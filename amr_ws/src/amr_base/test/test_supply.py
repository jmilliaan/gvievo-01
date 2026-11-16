"""Supply/brownout (unified plan WP-P7, H-P2-6, 2026-11-16): agv_core.canmon's supply edges and the
new-run refusal, against the profile's thresholds. Pure: no bus."""

from agv_core import alarms, canmon, config


def _nodes(*volts):
    """snapshot()["nodes"] with bus_v read as `volts` (None = no answer yet) on nodes 1, 2, ..."""
    p = canmon.MonitorPoller(list(range(1, len(volts) + 1)))
    for node, v in enumerate(volts, start=1):
        p.store(node, "bus_v", None if v is None else int(round(v * 10)))
    return p.snapshot(config.MONITOR_THRESHOLDS)["nodes"]


def test_the_profile_trip_reaches_the_snapshot():
    th = config.MONITOR_THRESHOLDS["bus_v"]
    assert th["trip_low"] == config.MON_BUS_V_TRIP_LOW < th["warn_low"] < th["warn"]
    assert _nodes(th["trip_low"])["1"]["bus_v"]["state"] == "trip"
    assert _nodes(th["warn_low"])["1"]["bus_v"]["state"] == "warn"


def test_supply_edges_name_the_side_and_the_worst_drive_decides():
    th = config.MONITOR_THRESHOLDS["bus_v"]
    mid = (th["warn_low"] + th["warn"]) / 2.0
    assert canmon.supply_event(_nodes(mid, mid)) is None
    assert canmon.supply_event(_nodes(None, None)) is None  # nothing read: no edge either way
    code, level, detail = canmon.supply_event(_nodes(mid, th["warn_low"] - 0.5))
    assert (code, level) == ("SUPPLY_LOW", 1) and "warn_low" in detail
    code, level, _ = canmon.supply_event(_nodes(th["trip_low"], th["warn_low"] - 0.5))
    assert (code, level) == ("SUPPLY_TOO_LOW", 2)
    assert canmon.supply_event(_nodes(th["warn"] + 0.5, mid))[0] == "SUPPLY_HIGH"
    # a sagging pack with a regen spike on the other drive reads as too low, never as regen
    assert canmon.supply_event(_nodes(th["trip_low"] - 1.0, th["warn"] + 0.5))[0] == "SUPPLY_TOO_LOW"


def test_the_detail_is_stable_within_a_state_so_edge_does_not_re_emit():
    # drive_node `_edge` compares (code, detail): a voltage in the detail would emit an event
    # on every 0.1 V step at 1 Hz (2026-11-16)
    th = config.MONITOR_THRESHOLDS["bus_v"]
    mid = (th["warn_low"] + th["warn"]) / 2.0
    for code, a, b in (("SUPPLY_LOW", th["warn_low"] - 0.1, th["warn_low"] - 0.7),
                       ("SUPPLY_TOO_LOW", th["trip_low"] - 0.2, th["trip_low"] - 1.3),
                       ("SUPPLY_HIGH", th["warn"] + 0.2, th["warn"] + 1.1)):
        ea, eb = canmon.supply_event(_nodes(a, mid)), canmon.supply_event(_nodes(mid, b))
        assert ea[0] == eb[0] == code and ea[2] == eb[2], (ea, eb)
        assert f"{a:.1f}" not in ea[2] and f"{b:.1f}" not in eb[2]


def test_every_supply_code_is_in_the_catalogue_at_its_edge_level():
    for code in (canmon.SUPPLY_LOW, canmon.SUPPLY_TOO_LOW, canmon.SUPPLY_HIGH):
        assert code in alarms.CATALOGUE, code
    th = config.MONITOR_THRESHOLDS["bus_v"]
    for volts in ((th["warn_low"] - 0.1,), (th["trip_low"],), (th["warn"],)):
        code, level, _ = canmon.supply_event(_nodes(*volts))
        assert level == alarms.level(code), code


def test_a_new_run_is_refused_at_or_below_trip_low_only():
    trip = config.MON_BUS_V_TRIP_LOW
    assert canmon.supply_refusal([trip + 0.1, trip + 2.0], trip) == ""
    assert canmon.supply_refusal([None, None], trip) == ""  # an unread supply is not a refusal
    why = canmon.supply_refusal([trip + 2.0, trip], trip)
    assert why.startswith("battery too low") and f"{trip:.1f} V" in why
