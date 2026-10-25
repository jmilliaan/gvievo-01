#!/usr/bin/env python3
"""Drive both BLVD-KRD motors forward in Profile Velocity mode.

*** THIS MOVES HARDWARE. *** Refuses to run without --go.

Speed, ramp rate and duration are the TARGET_RPM / ACCEL_RPM_S / RUN_SECONDS
constants below; run without --go to have the actual values printed back at you
rather than trusting a number written in this docstring.

Object references (BLV-R CANopen edition, opman_can/blvr_canopen.md):
  6040h Controlword          6041h Statusword        :1412 / :1428
  6060h Modes of operation   3 = pv                  :4556
  6083h Profile acceleration (r/min)/s               :1634
  6084h Profile deceleration (r/min)/s               :1635
  60FFh Target velocity      r/min, signed           :1637
  606Ch Velocity actual value r/min, ro              :1619

Sequence per CiA 402: NMT Start -> Shutdown(06) -> Switch On(07) ->
Enable Operation(0F) with target 0, then ramp by writing 60FFh.
"""
import sys
import time

from agv_core.drivers.canbus.cia402 import (  # noqa: F401 - CW_*/SW_* re-exported
    CW_DISABLE_VOLTAGE,
    CW_ENABLE,
    CW_SHUTDOWN,
    CW_SWITCH_ON,
    ENABLE_SEQUENCE,
    PVCM_MOTION_EXTENSION,
    SW_FAULT,
    SW_REMOTE,
    SW_SPEED_IS_ZERO,
    decode_state,
    is_operation_enabled,
    preflight_report,
)
from agv_core.drivers.canbus.sdo import (  # noqa: F401 - sdo_write/nmt re-exported
    BAD,
    OK,
    WARN,
    bench_bus,
    guarded_sdo_write,
    nmt,
    sdo_int,
    sdo_read,
    sdo_write,
)

NODES = {1: "left", 2: "right"}
TARGET_RPM = 160        # 60FFh, signed: positive = forward
ACCEL_RPM_S = 400       # 6083h
DECEL_RPM_S = 400       # 6084h
RUN_SECONDS = 2.2
MAX_RPM_SANITY = 4000    # refuse obviously wrong setpoints


def w(bus, node, index, sub, value, size, what):
    ok, detail = guarded_sdo_write(bus, node, index, sub, value, size)
    if not ok:
        raise RuntimeError(f"node {node}: writing {what} ({index:04X}h) failed: {detail}")
    return ok


def statusword(bus, node):
    v = sdo_int(bus, node, 0x6041, 0)
    return None if v is None else v & 0xFFFF


def actual_rpm(bus, node):
    return sdo_int(bus, node, 0x606C, 0, signed=True)


def coast_to_stop(bus, quiet=False):
    """Best-effort: zero the setpoint, let the ramp run, then de-energise.

    Must never raise - this runs from the finally block.
    """
    for nid in NODES:
        try:
            guarded_sdo_write(bus, nid, 0x60FF, 0, 0, 4)
        except Exception:
            pass
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            if all((statusword(bus, n) or 0) & SW_SPEED_IS_ZERO for n in NODES):
                break
        except Exception:
            break
        time.sleep(0.05)
    for nid in NODES:
        for cw in (CW_SHUTDOWN, CW_DISABLE_VOLTAGE):
            try:
                guarded_sdo_write(bus, nid, 0x6040, 0, cw, 2)
            except Exception:
                pass
    if not quiet:
        print("    motors de-energised.")


def preflight(bus):
    print("[1] preflight")
    ok, lines = preflight_report(lambda n, i, sub: sdo_read(bus, n, i, sub),
                                 lambda n, i: sdo_int(bus, n, i, 0), NODES)
    for line in lines:
        print(f"    {line}")
    return ok


def arm(bus):
    print("\n[2] arming (target velocity held at 0)")
    nmt(bus, 0x01)  # broadcast Start Remote Node -> NMT Operational
    print("    NMT: all nodes -> Operational")
    for nid, label in NODES.items():
        w(bus, nid, 0x6060, 0, 3, 1, "modes of operation = pv")
        w(bus, nid, 0x6083, 0, ACCEL_RPM_S, 4, "profile acceleration")
        w(bus, nid, 0x6084, 0, DECEL_RPM_S, 4, "profile deceleration")
        w(bus, nid, 0x60FF, 0, 0, 4, "target velocity = 0")
        for cw, name in ENABLE_SEQUENCE:
            w(bus, nid, 0x6040, 0, cw, 2, name)
            time.sleep(0.05)
        sw = statusword(bus, nid)
        if sw is None:
            raise RuntimeError(f"node {nid} statusword unreadable after enable")
        state = decode_state(sw)
        flag = OK if is_operation_enabled(sw) else BAD
        print(f"    node {nid} ({label}): 0x{sw:04X} ({state}) {flag}")
        if not is_operation_enabled(sw):
            raise RuntimeError(f"node {nid} did not reach Operation enabled")


def run(bus):
    print(f"\n[3] ramping to {TARGET_RPM} r/min at {ACCEL_RPM_S} (r/min)/s, "
          f"holding {RUN_SECONDS:.0f} s")
    for nid in NODES:
        w(bus, nid, 0x60FF, 0, TARGET_RPM, 4, "target velocity")

    t0 = time.time()
    while (elapsed := time.time() - t0) < RUN_SECONDS:
        row = []
        for nid, label in NODES.items():
            sw, rpm = statusword(bus, nid), actual_rpm(bus, nid)
            if sw is None or rpm is None:
                raise RuntimeError(f"node {nid} stopped responding mid-run")
            if sw & SW_FAULT:
                raise RuntimeError(f"node {nid} entered FAULT (statusword 0x{sw:04X})")
            row.append(f"{label} {rpm:>6} rpm")
        print(f"    t={elapsed:5.1f}s   " + "   ".join(row))
        time.sleep(1.0)
    print(f"    hold complete ({RUN_SECONDS:.0f} s)")


def main():
    if "--go" not in sys.argv:
        print(__doc__)
        print(f"PLAN: nodes {list(NODES)} -> {TARGET_RPM:+} r/min, "
              f"accel {ACCEL_RPM_S} / decel {DECEL_RPM_S} (r/min)/s, "
              f"hold {RUN_SECONDS:.1f} s.")
        print("\nBoth setpoints are POSITIVE, which on THIS AGV is forward travel:")
        print("the wheels are opposite-handed, so equal positive velocities drive")
        print("it straight (vehicle.invert_left/invert_right in the profile carry the")
        print(f"same convention). {WARN}: re-verify on blocks after swapping a motor or driver -")
        print("if the two wheels turn opposite ways you will get a spin, not travel.")
        print("\nRe-run with --go to actually drive.")
        return 0

    if abs(TARGET_RPM) > MAX_RPM_SANITY:
        print(f"{BAD}: TARGET_RPM {TARGET_RPM} exceeds sanity limit")
        return 2

    opened = bench_bus("drive_forward")
    if opened is None:
        return 2
    _lock, bus = opened

    rc = 0
    armed = False
    try:
        if not preflight(bus):
            print(f"\n{BAD}: preflight failed, not driving.")
            return 1
        arm(bus)
        armed = True
        run(bus)
        print(f"\n[4] {OK}: run completed normally")
    except KeyboardInterrupt:
        print(f"\n\n{WARN}: interrupted - stopping motors")
        rc = 1
    except Exception as e:
        print(f"\n{BAD}: {e}")
        rc = 1
    finally:
        if armed:
            print("\n[stop] ramping down")
            coast_to_stop(bus)
        try:
            nmt(bus, 0x80)  # back to Pre-operational
        except Exception:
            pass
        bus.shutdown()
    return rc


if __name__ == "__main__":
    sys.exit(main())
