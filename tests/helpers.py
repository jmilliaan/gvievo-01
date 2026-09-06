"""Shared rig for the offline suite. No CAN, no hardware, no motion.

The plant simulation lives here because more than one module integrates against
it: it runs the REAL LineFollower against e_dot = v*theta + Ls*omega, including
the 1 mm sensor quantisation, the 50 Hz tick, the transport delay and the wheel
slew limit imposed by 6083h. That slew limit is what makes simulating worth the
trouble - an ideal plant that lets yaw follow the command instantly says
K_RATIO = 100 is fine, and on this vehicle that diverges at 0.8 m/s.

FAIL is shared state, deliberately. Every module appends to the same list so
run_all.py can report one verdict for the whole suite rather than eight.
"""
import math
import os
import pathlib
import struct
import sys

# Repo root, so a check that reads a source file keeps working wherever the
# suite is run from and wherever the module it inspects has been moved to.
ROOT = pathlib.Path(__file__).resolve().parent.parent
# Same flat layout the app uses - see the note in canworker.py.
for _d in ("", "core", "drivers", "drivers/canbus", "app"):
    sys.path.insert(0, str(ROOT / _d) if _d else str(ROOT))

import autopilot  # noqa: E402
import config  # noqa: E402
import kinematics  # noqa: E402
import motion  # noqa: E402

FAIL = []

# Counted so run_all.py can pin the total. A single-element list rather than an
# int because every test module imports this by value.
CHECKS = [0]

NO_TRACK = {"tracks": [], "has_track": False}


def check(name, cond, detail=""):
    CHECKS[0] += 1
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def sensor(pos_mm, n=1):
    """A TPDO1 decode shaped like canworker._sensor_json()."""
    return {"tracks": [{"index": i + 1, "pos_mm": pos_mm, "width": 10}
                       for i in range(n)],
            "has_track": True}


NO_TRACK = {"tracks": [], "has_track": False}


# ---------------------------------------------------------------------------
# plant simulation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# plant simulation
# ---------------------------------------------------------------------------

def simulate(base_rpm, e0_mm=30.0, seconds=12.0, driver_accel=2000.0,
             delay_s=0.020, sub_dt=0.0005, at_speed=True):
    """Closed-loop step response. Returns (overshoot_mm, settle_s, tail_rms_mm).

    at_speed pre-loads the ramp so the disturbance lands while already cruising.
    That is the demanding case and the realistic one: starting from rest lets the
    PID null most of the error before the vehicle has any speed, which flatters
    high gains badly.
    """
    f = autopilot.LineFollower()
    f.reset()

    y, theta = e0_mm / 1000.0, 0.0
    nl_act = nr_act = 0.0
    nl_cmd = nr_cmd = 0.0
    queue = []

    # The follower always ramps toward AUTO_RPM, so the cruise speed under test
    # has to BE AUTO_RPM or the vehicle spends the run decelerating.
    saved_rpm = config.AUTO_RPM
    config.AUTO_RPM = base_rpm
    if at_speed:
        f._v_rpm = base_rpm
        nl_act = nr_act = base_rpm
        nl_cmd = nr_cmd = base_rpm

    try:
        return _integrate(f, y, theta, nl_act, nr_act, nl_cmd, nr_cmd, queue,
                          seconds, driver_accel, delay_s, sub_dt, e0_mm)
    finally:
        config.AUTO_RPM = saved_rpm


def _integrate(f, y, theta, nl_act, nr_act, nl_cmd, nr_cmd, queue,
               seconds, driver_accel, delay_s, sub_dt, meas_mm):
    t = 0.0
    next_tick = next_frame = 0.0
    over = 0.0
    settle = None
    tail = []

    while t < seconds:
        if t >= next_frame:                       # 100 Hz, quantised to 1 mm
            next_frame += 0.01
            # The MLS reports where the LINE is relative to the SENSOR, which is
            # the NEGATIVE of where the sensor is relative to the line. Getting
            # this backwards used to cancel against INVERT_ERROR=False and the
            # sim converged for the wrong reason; with the real polarity now
            # measured on the machine, the model has to match it.
            meas_mm = -round((y + config.SENSOR_LOOKAHEAD_M
                              * math.sin(theta)) * 1000.0)
        if t >= next_tick:                        # 50 Hz control tick
            next_tick += config.DT_NOMINAL_S
            l, r, _ = f.update(sensor(meas_mm), 0.0, config.DT_NOMINAL_S, True)
            queue.append((t + delay_s, l, r))
        while queue and queue[0][0] <= t:
            _, nl_cmd, nr_cmd = queue.pop(0)

        # 6083h slews each wheel; this is the constraint the ideal model misses.
        step = driver_accel * sub_dt
        nl_act += max(-step, min(step, nl_cmd - nl_act))
        nr_act += max(-step, min(step, nr_cmd - nr_act))

        # Forward speed comes from the wheels, not from a constant - otherwise
        # speed_reduction has no effect on the plant and the controller and the
        # vehicle disagree about how fast it is going.
        v, omega = kinematics.wheels_to_body(nl_act, nr_act)
        y += v * math.sin(theta) * sub_dt
        theta += omega * sub_dt
        t += sub_dt

        e = y + config.SENSOR_LOOKAHEAD_M * math.sin(theta)
        over = max(over, -e)
        if abs(e) < 0.002 and settle is None and t > 0.5:
            settle = t
        elif abs(e) >= 0.002:
            settle = None
        if t > seconds - 2.0:
            tail.append(e)

    rms = math.sqrt(sum(x * x for x in tail) / len(tail)) * 1000.0 if tail else 0.0
    return over * 1000.0, settle, rms


# ---------------------------------------------------------------------------
# canworker re-entrancy (regression)
# ---------------------------------------------------------------------------

class _FakeRaw:
    """A bus that behaves like the real one during an SDO read while the MLS is
    streaming: a couple of sensor frames are already queued, then the SDO reply
    lands, then the queue drains empty."""

    def __init__(self):
        self.pending = [("pdo",), ("pdo",)]

    def send(self, m):
        if 0x600 <= m.arbitration_id <= 0x67F:
            self.pending += [("pdo",), ("sdo", m.arbitration_id - 0x600)]

    def recv(self, timeout=None):
        import can
        if not self.pending:
            return None
        kind = self.pending.pop(0)
        if kind[0] == "pdo":
            return can.Message(arbitration_id=config.TPDO1_COB,
                               data=bytes(8), is_extended_id=False)
        return can.Message(arbitration_id=0x580 + kind[1],
                           data=bytes([0x43, 0, 0, 0]) + struct.pack("<I", 7),
                           is_extended_id=False)

    def shutdown(self):
        pass


def _why(g, index, value=0x40, sub=None):
    """The refusal message, so a test can assert it explains itself."""
    try:
        g.check(index, value, sub)
        return ""
    except g.ForbiddenWrite as e:
        return str(e)
