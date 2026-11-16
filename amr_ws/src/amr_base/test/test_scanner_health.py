"""WP-E4: the scanners' own diagnosis (amr_base.scanner_health). No ROS.

The fixture is a /diagnostics message in `ros2 topic echo` form, built from the
sick_safetyscanners2 1.0.5 driver's sensorDiagnostics (key names, "True"/"False" booleans,
"<node>: State", hardware_id = the sensor IP) - reconstructed from the driver's format, not
recorded on the vehicle. Re-record it there (`ros2 topic echo --once /diagnostics`) when the
scanner is next on the bench; a key that moved fails here first.
"""

import copy

import yaml
from agv_core import alarms

from amr_base import scanner_health as sh

ECHO = r"""
header:
  stamp:
    sec: 1763281234
    nanosec: 512000000
  frame_id: ''
status:
- level: "\0"
  name: 'sick_safetyscanners2_node: State'
  message: ''
  hardware_id: 192.168.3.10
  values:
  - key: Version version
    value: V
  - key: Version major version
    value: '1'
  - key: Version minor version
    value: '2'
  - key: Version release
    value: '0'
  - key: Serial number of device
    value: '22140357'
  - key: Serial number of channel plug
    value: '22130981'
  - key: App checksum
    value: 9A1C44E0
  - key: Overall checksum
    value: 3F0B12D7
  - key: Channel number
    value: '0'
  - key: Sequence number
    value: '1184522'
  - key: Scan number
    value: '2369044'
  - key: Timestamp date
    value: '20408'
  - key: Timestamp time
    value: '41211087'
  - key: Run mode active
    value: 'True'
  - key: Standby mode active
    value: 'False'
  - key: Contamination warning
    value: 'False'
  - key: Contamination error
    value: 'False'
  - key: Reference contour status
    value: 'False'
  - key: Manipulation status
    value: 'False'
  - key: Current monitoring case no table 1
    value: '1'
  - key: Current monitoring case no table 2
    value: '0'
  - key: Current monitoring case no table 3
    value: '0'
  - key: Current monitoring case no table 4
    value: '0'
  - key: Application error
    value: 'False'
  - key: Device error
    value: 'False'
- level: "\0"
  name: 'sick_safetyscanners2_node: /scan topic status'
  message: ''
  hardware_id: 192.168.3.10
  values:
  - key: Events in window
    value: '170'
  - key: Events since startup
    value: '2369044'
  - key: Duration of window (s)
    value: '10.002'
  - key: Actual frequency (Hz)
    value: '16.996'
  - key: Target frequency (Hz)
    value: '17.0'
- level: "\0"
  name: 'sick_safetyscanners2_rear_node: State'
  message: ''
  hardware_id: 192.168.3.11
  values:
  - key: Contamination warning
    value: 'False'
  - key: Contamination error
    value: 'False'
  - key: Current monitoring case no table 1
    value: '3'
  - key: Application error
    value: 'False'
  - key: Device error
    value: 'False'
- level: "\0"
  name: 'drive_node: can/bus'
  message: ''
  hardware_id: can0
  values:
  - key: Contamination error
    value: 'True'
"""


def stored(changes=None, echo=ECHO):
    """The message as amr_web.adapter._on_diag stores it: {name: {..., "values": {k: v}}}.
    changes: {(name, key): value} edits a value; {(name, "level"): n} the level."""
    msg = yaml.safe_load(echo)
    out = {}
    for st in msg["status"]:
        d = {
            "name": st["name"],
            "hardware_id": str(st["hardware_id"]),
            "level": ord(st["level"]),
            "message": st["message"],
            "values": {kv["key"]: kv["value"] for kv in st["values"]},
            "age_s": 0.4,
        }
        out[d["name"]] = d
    for (name, key), value in (changes or {}).items():
        if key in ("level", "message", "age_s"):
            out[name][key] = value
        else:
            out[name]["values"][key] = value
    return out


F = "sick_safetyscanners2_node: State"
R = "sick_safetyscanners2_rear_node: State"


def test_the_fixture_is_healthy_and_the_keys_are_the_drivers():
    d = stored()
    assert sh.rows(d, rear_scanner=True) == []
    v = d[F]["values"]
    for key in (sh.KEY_CONTAMINATION_WARNING, sh.KEY_CONTAMINATION_ERROR, sh.KEY_APPLICATION_ERROR,
                sh.KEY_DEVICE_ERROR, sh.KEY_CASE):
        assert key in v, key
    assert sh.scanner_of(F) == sh.FRONT and sh.scanner_of(R) == sh.REAR
    assert sh.scanner_of("sick_safetyscanners2_node: /scan topic status") == sh.FRONT
    assert sh.scanner_of("drive_node: can/bus") is None
    # the raw message's [{key, value}] list reads the same
    raw = {"name": F, "level": 0, "values": [{"key": sh.KEY_CONTAMINATION_ERROR, "value": "True"}]}
    assert sh.rows([raw]) == [("SCANNER_CONTAMINATED", "front: contamination error")]


def test_contamination_error_and_warning():
    d = stored({(F, sh.KEY_CONTAMINATION_ERROR): "True", (F, sh.KEY_CONTAMINATION_WARNING): "True"})
    assert sh.rows(d) == [("SCANNER_CONTAMINATED", "front (192.168.3.10): contamination error")]
    d = stored({(F, sh.KEY_CONTAMINATION_WARNING): "True"})
    assert sh.rows(d) == [("SCANNER_DIRTY", "front (192.168.3.10): contamination warning")]


def test_device_and_application_errors_and_an_error_level():
    d = stored({(F, sh.KEY_DEVICE_ERROR): "True", (F, "level"): 2, (F, "message"): "Device error"})
    assert sh.rows(d) == [("SCANNER_ERROR", "front (192.168.3.10): device error")]
    d = stored({(F, sh.KEY_APPLICATION_ERROR): "True"})
    assert sh.rows(d) == [("SCANNER_ERROR", "front (192.168.3.10): application error")]
    d = stored({(F, "level"): 2, (F, "message"): "Invalid data header received"})
    assert sh.rows(d) == [("SCANNER_ERROR", "front (192.168.3.10): Invalid data header received")]


def test_rows_rank_above_the_field_rows_worst_first():
    """A dirty window or a device error is WHY the protective field reads violated: the rows
    sort above FIELD_PROTECTIVE / FIELD_BLOCKED by severity, SCANNER_DIRTY excepted (running)."""
    d = stored({(F, sh.KEY_CONTAMINATION_ERROR): "True", (F, sh.KEY_DEVICE_ERROR): "True"})
    ov = {sh.FRONT: {"config_state": 3, "error_info_code": 0x0B000012}}
    got = [c for c, _ in sh.rows(d, overview=ov)]
    assert got == ["SCANNER_ERROR", "SCANNER_CONTAMINATED", "SCANNER_CONFIG_UNVERIFIED"]
    order = alarms.SEVERITY_ORDER
    for code in sh.RANK:
        assert code in alarms.CATALOGUE, code
        if code != "SCANNER_DIRTY":
            assert order[alarms.get(code).severity] < order[alarms.get("FIELD_PROTECTIVE").severity], code
    assert "error code 0x0B000012" in dict(sh.rows(d, overview=ov))["SCANNER_ERROR"]


def test_config_state_from_status_overview():
    d = stored()
    assert sh.rows(d, overview={sh.FRONT: {"config_state": 5}}) == []
    assert sh.rows(d, overview={sh.FRONT: {"config_state": 3}}) == [
        ("SCANNER_CONFIG_UNVERIFIED", "front (192.168.3.10): config_state 3 (not verified)")]
    assert sh.rows(d, overview={sh.FRONT: {"config_state": None}})[0][0] == "SCANNER_CONFIG_UNVERIFIED"
    assert sh.rows(d, overview={sh.REAR: {"config_state": 3}}) == [], "rear not fitted"


def test_rear_rows_only_with_the_rear_scanner_and_keyed_per_scanner():
    d = stored({(R, sh.KEY_CONTAMINATION_ERROR): "True"})
    assert sh.rows(d, rear_scanner=False) == []
    want = [("SCANNER_CONTAMINATED", "rear (192.168.3.11): contamination error")]
    assert sh.rows(d, rear_scanner=True) == want
    both = stored({(R, sh.KEY_CONTAMINATION_ERROR): "True", (F, sh.KEY_CONTAMINATION_ERROR): "True"})
    (row,) = sh.rows(both, rear_scanner=True)
    assert row[0] == "SCANNER_CONTAMINATED", "one row per code"
    assert "front (" in row[1] and "rear (" in row[1], "both scanners named"


def test_last_known_values_are_not_reported_without_a_fresh_scan():
    """The State keeps its last values after a data loss: gated on the caller's scan age and on
    the status's own age; STALE (no packet yet) is SCANNER_SILENT's, not a row here."""
    d = stored({(F, sh.KEY_CONTAMINATION_ERROR): "True"})
    assert sh.rows(d, scan_fresh={sh.FRONT: False}) == []
    assert sh.rows(d, scan_fresh={}) == []
    assert sh.rows(d, scan_fresh={sh.FRONT: True})[0][0] == "SCANNER_CONTAMINATED"
    old = copy.deepcopy(d)
    old[F]["age_s"] = 12.0
    assert sh.rows(old) == []
    stale = stored({(F, "level"): 3, (F, "message"): "Waiting for data"})
    assert sh.rows(stale) == [] and sh.front_case(stale) is None
    assert sh.rows({}) == [] and sh.rows([]) == []


def test_the_front_case_is_read_for_showing():
    assert sh.front_case(stored()) == 1
    assert sh.front_case(stored({(F, sh.KEY_CASE): "x"})) is None
    assert sh.front_case({}) is None


def test_survey_scan_gap_is_flagged_once_per_gap():
    """H-P1-12: 0.1 s ok, 2.0 s flagged once, a fresh scan closes the gap."""
    g = sh.ScanGap()
    assert g.update(0.1) is None
    text = g.update(2.0)
    assert text and "2.0 s" in text and "gap" in text
    assert g.update(2.5) is None, "once per gap"
    assert g.update(0.05) is None
    assert g.update(1.5) is not None, "a new gap is flagged again"
    assert g.update(None) is None
    assert sh.ScanGap.CODE in alarms.CATALOGUE
