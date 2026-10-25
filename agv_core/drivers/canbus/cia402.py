"""CiA 402 drive profile: control/status bits, the state decode, the enable sequence
and the preflight verdict. Shared by the bus owner (amr_base.canopen) and the bench
tools. Pure: no bus, no python-can.

Object references (BLV-R CANopen edition, opman_can/blvr_canopen.md):
  6040h Controlword :1412   6041h Statusword :1428   6060h Modes of operation :4556
"""

# Controlword bit 13 (PVCM): 0 = motion extension, 1 = normal (opman_can:1667).
# MOTION EXTENSION: this vehicle's motor is a BLMR6400SKM-GFV-B, 400 W on a 1:30
# gearhead, and the Function Edition says that combination must use motion
# extension - in normal mode a hard decel while demand and actual velocity differ
# can damage the motor (opman_fun:2951, 3121). It is also what the RPDO stream
# sends (CW_OPERATION_ENABLED), so the arm sequence and every later setpoint agree.
PVCM_MOTION_EXTENSION = 0
CW_OPERATION_ENABLED = 0x000F
CW_ENABLE = CW_OPERATION_ENABLED | (PVCM_MOTION_EXTENSION << 13)   # bit12=0 => continuous velocity
CW_SWITCH_ON = 0x0007
CW_SHUTDOWN = 0x0006
CW_DISABLE_VOLTAGE = 0x0000

SW_FAULT = 1 << 3
SW_REMOTE = 1 << 9
SW_SPEED_IS_ZERO = 1 << 12

OPERATION_ENABLED_MASK, OPERATION_ENABLED = 0x6F, 0x27

MODE_PP, MODE_PV = 1, 3

# Shutdown -> Switch On -> Enable Operation, written in this order with the target at 0.
ENABLE_SEQUENCE = (
    (CW_SHUTDOWN, "Shutdown"),
    (CW_SWITCH_ON, "Switch On"),
    (CW_ENABLE, "Enable Operation"),
)

# Statusword (6041h) state decode: (mask, value, name), first match wins.
CIA402_STATES = [
    (0x4F, 0x00, "Not ready to switch on"),
    (0x4F, 0x40, "Switch on disabled"),
    (0x6F, 0x21, "Ready to switch on"),
    (0x6F, 0x23, "Switched on"),
    (0x6F, 0x27, "Operation enabled"),
    (0x6F, 0x07, "Quick stop active"),
    (0x4F, 0x0F, "Fault reaction active"),
    (0x4F, 0x08, "FAULT"),
]


def decode_state(sw):
    """The CiA 402 state by its whole masked pattern. Bit 5 (QS) is NOT a flag on its
    own: Operation enabled is 0x27 with bit 5 SET, Quick stop active 0x07 with it
    CLEAR, so read as active-high it would be exactly backwards."""
    for mask, val, name in CIA402_STATES:
        if sw & mask == val:
            return name
    return f"unknown (0x{sw:04X})"


def is_operation_enabled(sw):
    return sw is not None and (sw & OPERATION_ENABLED_MASK) == OPERATION_ENABLED


def preflight_report(read_sdo, read, nodes):
    """Can these drives be armed? Returns (ok, lines). Reads only.

    `read_sdo(node, index, sub)` is an sdo_read bound to a bus (status, payload,
    note, latency); `read(node, index)` returns an unsigned int or None.
    """
    ok, lines = True, []
    for nid, label in nodes.items():
        st, _, note, _ = read_sdo(nid, 0x1000, 0)
        if st is None:
            lines.append(f"node {nid} ({label}): not responding")
            ok = False
            continue
        if "COLLISION" in note:
            lines.append(f"node {nid} ({label}): {note}")
            ok = False
            continue
        err, sw = read(nid, 0x1001), read(nid, 0x6041)
        if err is None or sw is None:
            lines.append(f"node {nid} ({label}): diagnostics unreadable")
            ok = False
            continue
        lines.append(f"node {nid} ({label}): error reg 0x{err:02X}, "
                     f"statusword 0x{sw:04X} ({decode_state(sw)})")
        if err:
            lines.append(f"  node {nid}: driver reports a fault - clear it first")
            ok = False
        if not sw & SW_REMOTE:
            lines.append(f"  node {nid}: Remote bit clear - controlword ignored (S-ON active, or MEXE02)")
            ok = False
        if sw & SW_FAULT:
            lines.append(f"  node {nid}: FAULT state")
            ok = False
    return ok, lines
