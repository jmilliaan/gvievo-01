#!/usr/bin/env python3
"""Which CANopen objects the navigation PC is allowed to WRITE.

can-monitoring-plan.txt section 8, and the doc calls it the most important
section in the file. CANopen is bidirectional, and the objects below can defeat
safety behaviour from a single stray frame:

  403Eh  Driver input command. R-IN6 defaults to FREE. Writing bit 6 RELEASES
         THE HOLDING BRAKE on BOTH drive wheels and de-excites the motors, with
         600 kg behind the hitch. A bug, a stale frame or a bad mask is enough.
  40D0h  Clear ETO. Re-excites the motor. Called automatically after a
         protective field clears, this IS an automatic restart - prohibited by
         ISO 3691-4.
  40C0h  Alarm reset, and 6040h bit 7 (fault reset). An alarm that clears
         itself is an alarm nobody learns about; repeated auto-reset of an
         overvoltage hides a real regen problem until it becomes a stoppage.
  1010h  Store parameters / 1011h Restore defaults. 1011h wipes configuration
         back to factory, including the safety-relevant stop parameters.
  40C6h  and the 4000h-4FFFh parameter block generally. Writing quick-stop
         rate, QSTOP action, ETO reset action or the overvoltage threshold from
         the nav stack is how the two drives silently diverge.

The posture is READ-MOSTLY: permit only the writes motion genuinely needs, deny
everything else by index, and assert it in a test. The deny-list is documented
because an assessor will ask for it.

Deliberately dependency-free, like the rest of canbus/.
"""


class ForbiddenWrite(Exception):
    """A write to an object the navigation PC must never touch."""


# Everything motion actually needs, and nothing else.
#   6040h controlword     - CiA 402 state machine (bit 7 masked, see below)
#   6060h modes           - set to pv at arm time
#   6083h/6084h ramps     - profile accel/decel, written per mode at arm
#   60FFh target velocity - the setpoint itself
#   1017h heartbeat       - producer heartbeat time; enabling it is what makes
#                           a dead drive distinguishable from an idle one, and
#                           it cannot influence motion.
ALLOWED = {
    0x6040: "controlword",
    0x6060: "modes of operation",
    0x6083: "profile acceleration",
    0x6084: "profile deceleration",
    0x60FF: "target velocity",
    0x1017: "producer heartbeat time",
}

# Named purely so a refusal can say WHY, rather than "not allowed".
FORBIDDEN = {
    0x403E: "driver input command - bit 6 is FREE and releases both brakes",
    0x40D0: "clear ETO - re-excites the motor; automatic restart is prohibited",
    0x40C0: "alarm reset - alarms must never be cleared automatically",
    0x1010: "store parameters",
    0x1011: "restore default parameters - wipes the safety-relevant config",
    0x40C6: "configuration",
}

# 6040h is allowed, but bit 7 of it is Fault reset, which is 40C0h by another
# name. Masked rather than refused, so the ordinary state-machine writes the
# arm sequence performs are unaffected.
CONTROLWORD_FAULT_RESET = 1 << 7

# ---------------------------------------------------------------------------
# PDO CONFIGURATION (CiA 301)
# ---------------------------------------------------------------------------
# Pushed drive feedback (TPDO), a PDO setpoint (RPDO) and the MLS yaw-rate TPDO
# all need these ranges, which the "not on the permitted-write list" rule
# refuses outright. Adding them to ALLOWED would open three holes, because
# *** A PDO IS A WRITE PATH BY ANOTHER NAME ***:
#
#   * Map 403Eh into an RPDO and a plain two-byte frame releases both brakes,
#     with no SDO write anywhere for the deny-list to see.
#   * Give an RPDO the COB-ID of other traffic and the drive obeys THAT traffic
#     as commands - on 18Ah, the MLS's own 50 Hz TPDO1 becomes a wheel speed.
#   * Give a TPDO the COB-ID of another node's RPDO and its status frames are
#     that node's commands.
#
# So each range is admitted on its own terms:
#
#   RPDO mapping   only an object that is itself writable by SDO, and never a
#                  PDO configuration object (which would let a frame remap or
#                  re-address a PDO).
#   TPDO mapping   any object. A TPDO is a read path - the device transmits.
#   COB-ID (sub 1) disabled, or an 11-bit id in its own kind's predefined range
#                  (CiA 301 7.3.5): RPDO 201h-57Fh, TPDO 181h-4FFh, matching
#                  the target node when the caller names it. Function codes
#                  never overlap, so a PDO addressed this way cannot collide
#                  with NMT, SYNC, EMCY, SDO, heartbeat or another PDO kind.
#   other comm subs transmission type, inhibit time, event timer, sync start:
#                  WHEN a PDO goes, not what it carries or who obeys it.
#
# The guard cannot see RPDO frames themselves. Whatever sends one carrying
# 6040h must put each controlword through check(0x6040, value), or bit 7 -
# fault reset - reaches the drive once per frame.
PDO_RANGES = (
    (0x1400, 0x15FF, "rpdo_comm"),
    (0x1600, 0x17FF, "rpdo_map"),
    (0x1800, 0x19FF, "tpdo_comm"),
    (0x1A00, 0x1BFF, "tpdo_map"),
)

# Sub 0 of a mapping object is the ENTRY COUNT (0-8), not an object reference.
# Writing 0 to it is the first step of every remap.
MAPPING_COUNT_SUB = 0
COB_ID_SUB = 1

# COB-ID entry bits (CiA 301 7.5.2.35).
COB_INVALID = 1 << 31               # the PDO does not exist
COB_EXTENDED = 1 << 29              # 29-bit identifier
COB_ID_MASK = 0x7FF
NODE_MASK = 0x7F

# Predefined connection set function codes, by PDO kind.
PDO_FUNCTION_CODES = {
    "rpdo_comm": (0x200, 0x300, 0x400, 0x500),
    "tpdo_comm": (0x180, 0x280, 0x380, 0x480),
}


def _pdo_kind(index):
    for lo, hi, kind in PDO_RANGES:
        if lo <= index <= hi:
            return kind
    return None


def _where(index, sub):
    return f"{index:04X}h" if sub is None else f"{index:04X}h:{sub:02X}"


def _check_rpdo_mapping(index, value, sub):
    """An RPDO mapping entry, validated against the deny-list it would bypass.

    An entry is a u32: index << 16 | subindex << 8 | bit length. Zero is an
    empty slot, which is how a mapping is shortened, and maps nothing.
    """
    if sub == MAPPING_COUNT_SUB:
        return None
    if sub is None or value is None:
        raise ForbiddenWrite(
            f"write to {_where(index, sub)} refused: an RPDO mapping entry is "
            f"checked by its subindex and value - sub 0 is the entry count, "
            f"sub 1-8 name the object a frame will write")
    if value == 0:
        return None
    mapped = (value >> 16) & 0xFFFF
    if _pdo_kind(mapped) is not None:
        raise ForbiddenWrite(
            f"RPDO mapping {_where(index, sub)} would map {mapped:04X}h, a PDO "
            f"configuration object: a frame could then remap or re-address a "
            f"PDO (can-monitoring-plan.txt section 8)")
    try:
        check(mapped)
    except ForbiddenWrite as e:
        raise ForbiddenWrite(
            f"RPDO mapping {_where(index, sub)} would map {mapped:04X}h, which "
            f"is not writable: {e}. An RPDO is a write path - a plain CAN frame "
            f"would do what a direct SDO write is refused") from None
    return None


def _check_pdo_comm(kind, index, value, sub, node):
    """A PDO communication parameter. Only the COB-ID decides who obeys it."""
    if sub is None:
        raise ForbiddenWrite(
            f"write to {index:04X}h refused: a PDO communication parameter is "
            f"checked by its subindex - sub 1 is the COB-ID")
    if sub != COB_ID_SUB:
        return None
    if value is None:
        raise ForbiddenWrite(
            f"write to {_where(index, sub)} refused: a COB-ID cannot be checked "
            f"without its value")
    if value & COB_INVALID:
        return None                     # a disabled PDO sends and obeys nothing
    what = "RPDO" if kind == "rpdo_comm" else "TPDO"
    if value & COB_EXTENDED:
        raise ForbiddenWrite(
            f"{what} COB-ID {_where(index, sub)} = 0x{value:08X} refused: "
            f"29-bit identifiers are not used on this bus")
    cob = value & COB_ID_MASK
    function, cob_node = cob & ~NODE_MASK & COB_ID_MASK, cob & NODE_MASK
    if function not in PDO_FUNCTION_CODES[kind] or cob_node == 0:
        raise ForbiddenWrite(
            f"{what} COB-ID {_where(index, sub)} = {cob:03X}h refused: outside "
            f"the {what} identifier ranges, so it could "
            + ("make the drive obey other traffic as commands"
               if kind == "rpdo_comm" else
               "turn this node's transmissions into another node's commands")
            + " (can-monitoring-plan.txt section 8)")
    if node is not None and cob_node != node:
        raise ForbiddenWrite(
            f"{what} COB-ID {_where(index, sub)} = {cob:03X}h refused on node "
            f"{node}: that identifier belongs to node {cob_node}")
    return None


def check(index, value=None, sub=None, node=None):
    """Raise ForbiddenWrite unless this object may be written. Else return None.

    Called on EVERY write path. A denied write raises rather than being quietly
    dropped: silently ignoring a command that a caller believed had landed is
    its own hazard.

    `sub` and `node` matter only for PDO configuration - see PDO_RANGES. A
    mapping entry or COB-ID with no subindex is refused rather than guessed.
    """
    if index in FORBIDDEN:
        raise ForbiddenWrite(
            f"write to {index:04X}h refused: {FORBIDDEN[index]} "
            f"(can-monitoring-plan.txt section 8)")
    # The whole manufacturer parameter block. 40D0h/40C0h/40C6h are named above
    # for a better message; this catches every other 4xxxh index, which is what
    # keeps the left/right configuration from diverging.
    if 0x4000 <= index <= 0x4FFF:
        raise ForbiddenWrite(
            f"write to {index:04X}h refused: driver parameters are changed by a "
            f"controlled maintenance procedure, not by the vehicle controller "
            f"(can-monitoring-plan.txt section 8)")
    # Admitted by rule rather than listed: ALLOWED stays the set of objects
    # motion writes directly.
    kind = _pdo_kind(index)
    if kind == "rpdo_map":
        return _check_rpdo_mapping(index, value, sub)
    if kind == "tpdo_map":
        return None
    if kind is not None:
        return _check_pdo_comm(kind, index, value, sub, node)
    if index not in ALLOWED:
        raise ForbiddenWrite(
            f"write to {index:04X}h refused: not on the permitted-write list "
            f"{sorted(f'{i:04X}h' for i in ALLOWED)}")
    if index == 0x6040 and value is not None and value & CONTROLWORD_FAULT_RESET:
        raise ForbiddenWrite(
            "controlword bit 7 (fault reset) refused: an alarm must be cleared "
            "by a deliberate operator acknowledgment, never by the nav stack "
            "(can-monitoring-plan.txt section 8)")
    return None


def is_allowed(index, value=None, sub=None, node=None):
    """Boolean form, for tests and for reporting the list in the UI."""
    try:
        check(index, value, sub, node)
        return True
    except ForbiddenWrite:
        return False
