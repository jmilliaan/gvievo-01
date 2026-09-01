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


def check(index, value=None):
    """Raise ForbiddenWrite unless this object may be written. Else return None.

    Called on EVERY write path. A denied write raises rather than being quietly
    dropped: silently ignoring a command that a caller believed had landed is
    its own hazard.
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


def is_allowed(index, value=None):
    """Boolean form, for tests and for reporting the list in the UI."""
    try:
        check(index, value)
        return True
    except ForbiddenWrite:
        return False
