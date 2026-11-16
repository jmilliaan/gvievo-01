"""Drive state strings (unified plan WP-T1, H-P3-1, 2026-11-16).

DriveStatus.left/right_state is cia402.decode_state()'s text, read by string compare in
amr_base.drive_state, emergency.sto_held and readiness.drives_ok. A fixture or fake that spells
a state its own way ("Operation enabled (simulated)", "OPERATION_ENABLED") tests a string the
vehicle never sends. Here the states are built from real statuswords, their classification is
pinned, and every hand-spelt state literal in the test fixtures and the sim fakes is an exact
known set. Pure: no rclpy.
"""

import ast
import re
from pathlib import Path

from agv_core.drivers.canbus.cia402 import CIA402_STATES, decode_state

from amr_base import drive_state as ds
from amr_base import emergency
from amr_bringup import readiness as rd

# Real statuswords (BLV-R: bit 9 remote, bit 4 voltage enabled, bit 12 speed zero where it is set).
WORDS = {
    0x0200: "Not ready to switch on",
    0x0250: "Switch on disabled",  # the safety chain holds STO
    0x0221: "Ready to switch on",
    0x0231: "Ready to switch on",
    0x0233: "Switched on",
    0x0637: "Operation enabled",
    0x1637: "Operation enabled",  # at standstill
    0x0217: "Quick stop active",
    0x021F: "Fault reaction active",
    0x0218: "FAULT",
    0x0238: "FAULT",
}
UNKNOWN = decode_state(0x0001)
UNKNOWN_RE = re.compile(r"^unknown \(0x[0-9A-F]{4}\)$")
# What drive_node can publish: a decoded state, STALE (TPDO1 stopped), "-" (canopen
# DriveTelemetry.state before any statusword), "" (an unset message field).
PUBLISHED = {decode_state(w) for w in WORDS} | {ds.STALE, "-", ""}

SRC = Path(__file__).resolve().parents[2]
# Calls that take drive states, and which positional arguments are states (None = all).
STATE_ARGS = {"torque_off": (1, 2), "has_fault": None, "drives_ok": (2, 3), "sto_held": (0, 1)}
STATE_FIELDS = ("left_state", "right_state")

# Hand-spelt literals that are not a string drive_node publishes: {(file, literal)}. Exact, so a
# new one fails here and a fixed one must be taken off. Empty since 2026-11-16 (the sim's
# "(simulated)" suffix, "Fault", "OPERATION_ENABLED" and "x" were replaced by real strings).
KNOWN_HAND_SPELT: set = set()


def test_every_table_state_comes_from_a_real_statusword():
    for sw, name in WORDS.items():
        assert decode_state(sw) == name, hex(sw)
    assert {n for _, _, n in CIA402_STATES} == set(WORDS.values())
    assert UNKNOWN_RE.match(UNKNOWN), UNKNOWN


def test_the_shared_constants_are_the_decoded_strings():
    assert ds.OPERATION_ENABLED == decode_state(0x0637) == decode_state(0x1637)
    assert ds.SWITCH_ON_DISABLED == emergency.STO_STATE == decode_state(0x0250)
    assert ds.STANDBY_STATES == (decode_state(0x0231), decode_state(0x0233))
    assert rd.STANDBY_STATES == ds.STANDBY_STATES


def test_how_each_published_state_is_classified():
    enabled, sod = ds.OPERATION_ENABLED, ds.SWITCH_ON_DISABLED
    for s in sorted(PUBLISHED | {UNKNOWN}):
        assert ds.has_fault(s) == (s in ("FAULT", "Fault reaction active")), s
        assert ds.torque_off(False, s, s) == (s != enabled), s
        assert not ds.torque_off(False, s, enabled), f"{s}: a drive still enabled is not torque off"
        assert not ds.torque_off(True, s, s), s
        assert rd.drives_ok(False, ds.LINK_STANDBY, s, s) == (s in ds.STANDBY_STATES), s
        assert not rd.drives_ok(False, ds.LINK_FAULT, s, s), s
        held = emergency.sto_held(s, s, "standby", 0.1)
        assert held == (None if s == "" else s == sod), s


def _literals(node):
    """String constants a state expression can evaluate to (through `a if c else b` / `or`)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _literals(node.body) + _literals(node.orelse)
    if isinstance(node, ast.BoolOp):
        return [s for v in node.values for s in _literals(v)]
    return []


def _state_literals(tree):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr in STATE_FIELDS for t in node.targets):
            out += _literals(node.value)
        elif isinstance(node, ast.Call):
            out += [s for k in node.keywords if k.arg in STATE_FIELDS for s in _literals(k.value)]
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name in STATE_ARGS:
                idx = STATE_ARGS[name]
                out += [s for i, a in enumerate(node.args) if idx is None or i in idx for s in _literals(a)]
    return out


def _sources():
    yield from sorted(SRC.glob("*/test/*.py"))
    yield from sorted(SRC.glob("amr_sim/amr_sim/*.py"))


def test_fixtures_and_fakes_spell_states_as_drive_node_publishes_them():
    found, scanned = set(), 0
    for path in _sources():
        scanned += 1
        for s in _state_literals(ast.parse(path.read_text(encoding="utf-8"))):
            if s not in PUBLISHED and not UNKNOWN_RE.match(s):
                found.add((path.relative_to(SRC).as_posix(), s))
    assert scanned > 50, f"scanned {scanned} files under {SRC}: wrong root?"
    assert found == KNOWN_HAND_SPELT, f"new: {sorted(found - KNOWN_HAND_SPELT)}; " \
                                      f"fixed, take off the list: {sorted(KNOWN_HAND_SPELT - found)}"


def test_the_scan_sees_each_form_a_fixture_uses():
    src = ('m.left_state = m.right_state = "A" if t else "B"\n'
           'DriveStatus(left_state="C", right_state=x)\n'
           'ds.torque_off(False, "D", "E")\nhas_fault("F")\n'
           'drives_ok(False, "standby", "G", "H")\nsto_held("I", "J", "armed", 0.1)\n')
    assert sorted(_state_literals(ast.parse(src))) == list("ABCDEFGHIJ")
