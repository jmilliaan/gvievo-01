#!/usr/bin/env python3
"""Read-only SDO probe for the bench session (unified coding plan WP-0B, §5).

    python3 -m agv_core.drivers.canbus.sdo_probe NODE:INDEX:SUB [...]
    python3 -m agv_core.drivers.canbus.sdo_probe --preset mls-tpdo
    python3 -m agv_core.drivers.canbus.sdo_probe --preset drive-health

NODE and SUB are decimal or 0x-hex, INDEX is hex (`10:1800:5`, `1:0x603F:0`).
Uploads only: no download, no NMT, and no --go, because there is nothing to
arm. It takes the CAN owner lock, so it refuses while amr.service holds can0
(exit 2, nothing sent). A write-shaped argument (`1:6040:0=6`) is an argparse
error. Every read prints hex and decimal, the abort code, or the timeout.
"""
import argparse
import sys

from agv_core.drivers.canbus import sdo


def _subs(index, subs):
    return [(index, s) for s in subs]


# §5 of manuals/unified-coding-plan.md says what each answer decides.
PRESETS = {
    "mls-tpdo": [
        (10, [*_subs(0x1800, (1, 2, 3, 5)), *_subs(0x1806, (1, 2, 5)),
              *_subs(0x1A06, range(9)), *_subs(0x1A00, range(9))]),
    ],
    "drive-health": [
        (node, [*_subs(0x1802, (1, 2, 3, 5)), *_subs(0x1803, (1, 2, 3, 5)),
                *_subs(0x1A02, range(9)), *_subs(0x1A03, range(9)),
                (0x407B, 0), (0x60FD, 0), (0x603F, 0), *_subs(0x1003, range(9)),
                (0x1016, 1), (0x1017, 0), (0x1001, 0), (0x6041, 0)])
        for node in (1, 2)
    ],
}


def parse_target(text):
    """'NODE:INDEX:SUB' -> (node, index, sub). Raises ValueError, naming why."""
    if "=" in text:
        raise ValueError(f"{text!r} looks like a write; this tool only reads")
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"{text!r}: want NODE:INDEX:SUB")
    node, index, sub = int(parts[0], 0), int(parts[1], 16), int(parts[2], 0)
    if not (1 <= node <= 127 and 0 <= index <= 0xFFFF and 0 <= sub <= 0xFF):
        raise ValueError(f"{text!r}: node 1-127, index 0000-FFFF, sub 0-255")
    return node, index, sub


def targets(args):
    out = []
    for name in args.preset or ():
        out += [(node, i, s) for node, objs in PRESETS[name] for i, s in objs]
    return out + list(args.objects)


def describe(status, payload, note):
    """One read's result as text: hex + decimal, the abort code, or why nothing came."""
    if status is True:
        v = sdo.u32(payload)
        return f"0x{v:0{2 * len(payload)}X}  ({v})" + ("" if note == "ok" else f"  [{note}]")
    if status is False and isinstance(payload, int):
        return f"ABORT 0x{payload:08X}"
    return f"no answer: {note}"


def run(bus, objs, timeout=0.4, out=print):
    """Read each (node, index, sub) once. Returns 0 if every read answered, 1 otherwise."""
    bad = 0
    for node, index, sub in objs:
        status, payload, note, _ = sdo.sdo_read(bus, node, index, sub, timeout=timeout)
        bad += status is not True
        out(f"node {node:>3}  {index:04X}h:{sub:02X}  {describe(status, payload, note)}")
    return 0 if not bad else 1


def _target(text):
    try:
        return parse_target(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only SDO probe. Stop amr.service first.")
    ap.add_argument("objects", nargs="*", type=_target, metavar="NODE:INDEX:SUB")
    ap.add_argument("--preset", action="append", choices=sorted(PRESETS))
    ap.add_argument("--timeout", type=float, default=0.4)
    args = ap.parse_args(argv)
    objs = targets(args)
    if not objs:
        ap.error("name at least one NODE:INDEX:SUB or a --preset")

    opened = sdo.bench_bus("sdo_probe")
    if opened is None:
        return 2
    _lock, bus = opened
    try:
        return run(bus, objs, timeout=args.timeout)
    finally:
        bus.shutdown()


if __name__ == "__main__":
    sys.exit(main())
