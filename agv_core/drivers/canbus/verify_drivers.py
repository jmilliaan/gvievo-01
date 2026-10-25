#!/usr/bin/env python3
"""Verify both BLVD-KRD drivers are alive on can0 at 125 kbps with distinct Node-IDs.

Read-only: issues SDO uploads (reads) and NMT nothing. Motors will not move.

Heartbeat (1017h) defaults to 0 on these drivers, so a passive listen is
expected to be silent. Liveness must be proven with SDO reads.

The bus helpers that used to live here are in sdo.py; the names stay importable
from this module so older bench notes keep working.
"""
import sys

from agv_core.drivers.canbus import verify_bus
from agv_core.drivers.canbus.sdo import (  # noqa: F401 - re-exported
    ADAPTER_PID,
    ADAPTER_SERIAL,
    ADAPTER_VID,
    BAD,
    BITRATE,
    CHANNEL,
    OK,
    WARN,
    bench_bus,
    claim_bus,
    find_adapter,
    open_bus,
    sdo_read,
    socketcan_ready,
    u32,
)

DEVICE_TYPE_EXPECTED = 0x00020192  # opman_can/blvr_canopen.md:2618
EXPECTED = {1: ("left driver", "BLVD-KRD", DEVICE_TYPE_EXPECTED),
            2: ("right driver", "BLVD-KRD", DEVICE_TYPE_EXPECTED)}
SCAN_RANGE = range(1, 17)  # ID-SEL can only produce 1..16
HINTS = {(2,): "right driver did not take ID-SEL0. Check the IN0 strap;"
               "\n         if it booted as node 1 both drivers share an address."}


def main():
    opened = bench_bus("verify_drivers")
    if opened is None:
        return 2
    _lock, bus = opened
    try:
        return verify_bus.run(bus, EXPECTED, SCAN_RANGE, scan_timeout=0.25, listen_s=2.0,
                              strict_type=True, hints=HINTS)
    finally:
        bus.shutdown()


if __name__ == "__main__":
    sys.exit(main())
