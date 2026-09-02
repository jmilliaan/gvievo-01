#!/usr/bin/env python3
"""Tune the SICK MLS magnetic line sensor on can0.

*** THIS WRITES TO THE SENSOR. *** Every write refuses to run without --go.
Reads are always safe and work in Pre-operational, so `show` and `events` need
no NMT state change and cannot disturb anything.

read_mls.py is deliberately read-only; this is its counterpart. Between them
they cover the commissioning procedure:

    tune_mls.py show                 what the sensor is set to, and what
                                     table 19 says that height should be
    tune_mls.py events               why the latched event flag is set
    tune_mls.py reset-event --go     clear it, so the next latch is news
    tune_mls.py calibrate --go       offset calibration, NO TAPE present
    tune_mls.py filter N --go        202Dh:3 averaging magnetic, 0-4
    tune_mls.py minlevel N --go      2025h detection threshold, digits
    tune_mls.py offset N --go        2026h zero point, mm
    tune_mls.py zero --go            202Ch teach current position as zero

Object references (MLS operating instructions 8021642, section 8.1.1):
  2021h:04 #LCP                 how many tracks are seen      p.31
  2023h    Track Level          3-bit field strength grade     p.31
  2024h    Field level          UINT16, full resolution        p.31
  2025h    Min. level           UINT16, default 200            p.31
  2026h    Offset               INT16, mm, sensor zero point   p.32
  202Bh    Trigger offset calibration   WO BOOL                p.33
  202Ch    Trigger zero position teach  WO BOOL                p.33
  202Dh:3  Averaging magnetic   UINT8, default 1               p.33 / p.48
  2080h:1  Reset event flag     WO                             p.34 / p.57
  2080h:2  Event source         RO, table 22                   p.57

Writes persist without a save command: 1010h:01 defaults to 2, which per
CiA 301 is "save autonomously on modification" - the same behaviour the BLVD
drivers have. There is no separate commit step to forget.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drive_forward import sdo_write  # noqa: E402
from verify_drivers import BAD, OK, WARN, open_bus, sdo_read  # noqa: E402

SENSOR_NODE = 10

# Table 19, p.43-44. (field level, line level, track level, mT, mm, filter).
# Descending by field level so the bracketing search below can walk it in order.
TABLE_19 = [
    (4500, 71, 7, 3.43, 10, 0), (2250, 35, 7, 1.72, 20, 0),
    (2000, 31, 7, 1.53, 22, 0), (1750, 28, 6, 1.34, 25, 0),
    (1500, 24, 5, 1.14, 28, 0), (1250, 20, 4, 0.95, 31, 0),
    (1000, 16, 3, 0.76, 37, 1), (750, 12, 2, 0.57, 44, 1),
    (500, 8, 1, 0.38, 55, 1), (450, 7, 0, 0.34, 60, 2),
    (350, 5, 0, 0.27, 70, 4),
]

FILTER_T90_MS = {0: 0, 1: 35, 2: 57, 3: 80, 4: 100}   # table 18, p.43
NOMINAL_MPS = 0.5      # roughly AUTO_RPM 1600 - only to render lag in mm

EVENT_SOURCE = {0: "no event", 2: "magnetic field", 4: "temperature",
                6: "magnetic field and temperature"}
MAG_CODE = {0: "no event", 1: "field fell below critical strength"}
TEMP_CODE = {0: "no event", 1: "below lower threshold (2070h:7)",
             2: "above upper threshold (2070h:6)"}

# 2026h is the only signed object this script touches.
SIGNED = {(0x2026, 0)} | {(0x2070, i) for i in range(1, 6)}


def rd(bus, node, index, sub, signed=False):
    st, val, _, _ = sdo_read(bus, node, index, sub)
    if not st or not val:
        return None
    return int.from_bytes(val, "little", signed=signed)


def wr(bus, node, index, sub, value, size, what):
    ok, detail = sdo_write(bus, node, index, sub, value, size)
    print(f"    {OK if ok else BAD}  {what}  ({index:04X}h:{sub:02X} = {value})"
          + ("" if ok else f"  {detail}"))
    return ok


def interp_distance(field):
    """Field level -> (mm, recommended filter) by table 19. None if off-scale."""
    if field is None or field >= TABLE_19[0][0]:
        return None, None
    for (fa, _, _, _, da, _), (fb, _, _, _, db, rb) in zip(TABLE_19, TABLE_19[1:]):
        if fb <= field <= fa:
            frac = (fa - field) / (fa - fb)
            # Recommended filter is the lower (weaker-signal) row's: table 19
            # gives a threshold, not a midpoint, so round toward more filtering.
            return db + (da - db) * (1 - frac), rb
    return None, None


# --- reads -------------------------------------------------------------------

def show_events(bus, node, indent="    "):
    src = rd(bus, node, 0x2080, 2)
    if src is None:
        print(f"{indent}{WARN} 2080h not readable - firmware < 5?")
        return None
    print(f"{indent}2080h:02 event source    {src} "
          f"({EVENT_SOURCE.get(src, 'reserved')})")
    if src & 0x02:
        c = rd(bus, node, 0x2080, 4)
        print(f"{indent}2080h:04 magnetic        {c} ({MAG_CODE.get(c, '?')})")
    if src & 0x04:
        c = rd(bus, node, 0x2080, 5)
        print(f"{indent}2080h:05 temperature     {c} ({TEMP_CODE.get(c, '?')})")
    show_temperature(bus, node, indent)
    return src


def show_temperature(bus, node, indent="    "):
    """2070h. Free forensics: :02 and :03 are lifetime extremes, not since-boot.

    The thermometer rides along with the IMU (2006h:02), so if the IMU has been
    disabled these read nothing and a temperature event cannot fire at all.
    """
    imu = rd(bus, node, 0x2006, 2)
    if imu == 0:
        print(f"{indent}2006h:02 MEMS           0 - IMU and thermometer OFF, so")
        print(f"{indent}                         a temperature event is impossible.")
        return
    now = rd(bus, node, 0x2070, 1, signed=True)
    if now is None:
        print(f"{indent}{WARN} 2070h not readable - firmware < 5?")
        return
    hi = rd(bus, node, 0x2070, 2, signed=True)
    lo = rd(bus, node, 0x2070, 3, signed=True)
    warn = "" if -20 <= now <= 70 else f"   {BAD} outside -20..70 C spec"
    print(f"{indent}2070h:01 temperature     {now} C{warn}")
    if hi is not None and lo is not None:
        # Lifetime, not since power-on: an excursion that happened months ago
        # still shows here, which is the only record of it that exists.
        print(f"{indent}2070h:02/03 lifetime     {lo} C .. {hi} C"
              + ("" if -20 <= lo and hi <= 70 else f"   {WARN} spec exceeded"))


def show(bus, node):
    field = rd(bus, node, 0x2024, 0)
    if field is None:
        print(f"{BAD} node {node} did not answer 2024h - is the sensor powered?")
        return 1
    nlcp = rd(bus, node, 0x2021, 4)
    level = rd(bus, node, 0x2023, 0)
    minlvl = rd(bus, node, 0x2025, 0)

    print("[1] live")
    tape = nlcp not in (0, None)
    print(f"    2024h field level        {field} "
          f"({field * 0.00076:.2f} mT){'' if tape else '   (no track present)'}")
    print(f"    2023h track level        {level}")
    print(f"    2021h:04 #LCP            {nlcp}"
          f"{'  <-- tape IS under the sensor' if tape else ''}")

    print("\n[2] geometry (table 19)")
    if tape:
        mm, want = interp_distance(field)
        if mm is None and field >= TABLE_19[0][0]:
            print(f"    field level {field} is above table 19's top row - "
                  f"closer than 10 mm to the tape")
        elif mm is None:
            print(f"    field level {field} is below table 19's bottom row - "
                  f"further than 70 mm, or this is not tape. A track is being")
            print("    reported, so 2025h min. level may be set too low.")
        else:
            print(f"    estimated working distance   ~{mm:.0f} mm to tape")
            print(f"    recommended 202Dh:3 filter   {want}")
    else:
        print("    no track - run this again with tape under the sensor to")
        print("    estimate the working distance.")
        if minlvl is not None and field < minlvl:
            print(f"    the {field} digits seen here are the vehicle's own static")
            print(f"    field. Below min. level {minlvl}, so no phantom track, but")
            print("    it is what `calibrate` removes.")

    print("\n[3] configuration")
    for index, sub, label, size in (
        (0x2006, 1, "2006h:01 variant TPDO1", 1),
        (0x2025, 0, "2025h min. level", 2),
        (0x2026, 0, "2026h zero offset (mm)", 2),
        (0x2027, 0, "2027h sensor flipped", 1),
        (0x202D, 1, "202Dh:01 first level (%)", 1),
        (0x202D, 2, "202Dh:02 last level (%)", 1),
        (0x202D, 3, "202Dh:03 averaging magnetic", 1),
        (0x202D, 5, "202Dh:05 track polarity", 1),
    ):
        v = rd(bus, node, index, sub, signed=(index, sub) in SIGNED)
        if v is None:
            continue
        note = ""
        if (index, sub) == (0x202D, 3):
            t90 = FILTER_T90_MS.get(v)
            if t90 is not None:
                note = (f"   t90 {t90} ms = {t90 * NOMINAL_MPS:.0f} mm of travel "
                        f"at {NOMINAL_MPS} m/s")
        print(f"    {label:<28} {v}{note}")

    print("\n[4] events and temperature")
    show_events(bus, node)
    return 0


# --- writes ------------------------------------------------------------------

def reset_event(bus, node):
    # The magnetic event fires whenever the field is below critical, which is
    # permanently true with no tape under the sensor - reset there and it
    # re-latches at once. Print the context so the [3] result can be read: only
    # "stayed clear WITH tape present" means anything.
    nlcp = rd(bus, node, 0x2021, 4)
    field = rd(bus, node, 0x2024, 0)
    print("[0] context")
    print(f"    #LCP {nlcp}, field level {field}")
    if nlcp == 0:
        print(f"    {WARN} no tape under the sensor. The magnetic event will")
        print("      re-latch immediately and the reset proves nothing. Park on")
        print("      the tape and re-run to make this a real test.")
    else:
        print(f"    {OK}  tape present - if the flag stays clear, this field")
        print("      strength is above the sensor's internal critical threshold.")

    print("\n[1] before")
    show_events(bus, node)
    print("\n[2] reset")
    if not wr(bus, node, 0x2080, 1, 1, 1, "reset event flag"):
        return 1
    time.sleep(0.2)
    print("\n[3] after")
    src = show_events(bus, node)
    if src and nlcp:
        print(f"\n    {WARN} re-latched WITH tape present. Field level {field} is")
        print("      below the sensor's critical strength, so the track position")
        print("      no longer meets the data sheet spec. Get closer to the tape,")
        print("      and keep 202Dh:3 filtering rather than reducing it.")
    elif src:
        print(f"\n    {WARN} still set, but with no tape present that is expected.")
        print("      Re-run on the tape for a meaningful result.")
    elif nlcp:
        print(f"\n    {OK}  stayed clear with tape present - field level {field} is")
        print("      above the critical threshold.")
    return 0


def calibrate(bus, node):
    """202Bh. The manual is explicit: not in the presence of the magnetic tape."""
    print("[1] pre-flight")
    nlcp = rd(bus, node, 0x2021, 4)
    field = rd(bus, node, 0x2024, 0)
    minlvl = rd(bus, node, 0x2025, 0)
    if nlcp is None or field is None:
        print(f"    {BAD} could not read the sensor - aborting.")
        return 1
    print(f"    #LCP {nlcp}, field level {field}, min. level {minlvl}")
    if nlcp != 0:
        print(f"\n    {BAD} a track is visible. The manual requires the offset")
        print("      calibration be run WITHOUT the magnetic tape - calibrating")
        print("      against the tape would teach the tape's field as the")
        print("      vehicle's own. Move the AGV clear of the tape and re-run.")
        return 1
    if minlvl is not None and field >= minlvl:
        print(f"\n    {WARN} field level {field} is at or above min. level "
              f"{minlvl} but")
        print("      no track is reported. Something magnetic is close. Move")
        print("      clear of it before calibrating.")
        return 1
    print(f"    {OK}  no track, field level is the vehicle's own static bias")

    print("\n[2] calibrate")
    print(f"    baseline field level: {field} digits")
    ok, detail = sdo_write(bus, node, 0x202B, 0, 1, 1)
    if ok:
        print(f"    {OK}  202Bh written")
    else:
        # The sensor restarts itself as part of this, so the confirmation can be
        # lost to the reset. A timeout here is not evidence of failure - the
        # re-read below is what decides.
        print(f"    {WARN} no SDO confirm ({detail}) - expected if it reset "
              f"immediately.")
        print("      Verifying by re-read rather than trusting the response.")

    print("\n[3] waiting for the restart")
    deadline = time.time() + 20.0
    back = None
    while time.time() < deadline:
        time.sleep(1.0)
        back = rd(bus, node, 0x2024, 0)
        if back is not None:
            break
        print("    ...")
    if back is None:
        print(f"    {BAD} sensor has not come back after 20 s. Power-cycle it "
              f"and re-read with read_mls.py snapshot.")
        return 1
    print(f"    {OK}  back after {20.0 - (deadline - time.time()):.0f} s")

    print("\n[4] result")
    settled = [rd(bus, node, 0x2024, 0) for _ in range(5)]
    settled = [v for v in settled if v is not None]
    if not settled:
        print(f"    {BAD} sensor answered once then stopped.")
        return 1
    lo, hi = min(settled), max(settled)
    print(f"    field level before   {field}")
    print(f"    field level after    {lo}-{hi} (5 reads)")
    if hi < field:
        print(f"\n    {OK}  the static bias dropped by {field - hi}-{field - lo} "
              f"digits.")
    else:
        print(f"\n    {WARN} no drop. Either there was little installation bias to")
        print("      remove, or the sensor moved between the two readings.")
    print("\n    Now put the tape back under the sensor and re-run")
    print("    `read_mls.py snapshot` to see the track with the bias removed.")
    return 0


def set_filter(bus, node, value):
    if value not in FILTER_T90_MS:
        print(f"{BAD} filter must be 0-4 (table 18); got {value}")
        return 1
    was = rd(bus, node, 0x202D, 3)
    t90 = FILTER_T90_MS[value]
    print(f"[1] 202Dh:03 averaging magnetic: {was} -> {value}")
    print(f"    t90 {t90} ms = {t90 * NOMINAL_MPS:.0f} mm of travel at "
          f"{NOMINAL_MPS} m/s")
    if not wr(bus, node, 0x202D, 3, value, 1, "averaging magnetic"):
        return 1
    print(f"\n[2] verify")
    now = rd(bus, node, 0x202D, 3)
    print(f"    reads back {now} {OK if now == value else BAD}")
    print("\n    Check the result with `read_mls.py stream` - watch LCP2 with the")
    print("    vehicle stationary, then rolling. Within +/-1 mm, keep it.")
    return 0 if now == value else 1


def set_minlevel(bus, node, value):
    if not 0 <= value <= 0xFFFF:
        print(f"{BAD} min. level must be 0-65535; got {value}")
        return 1
    was = rd(bus, node, 0x2025, 0)
    print(f"[1] 2025h min. level: {was} -> {value} digits")
    if not wr(bus, node, 0x2025, 0, value, 2, "min. level"):
        return 1
    now = rd(bus, node, 0x2025, 0)
    print(f"    reads back {now} {OK if now == value else BAD}")
    return 0 if now == value else 1


def set_offset(bus, node, value):
    if not -32768 <= value <= 32767:
        print(f"{BAD} offset must fit INT16; got {value}")
        return 1
    was = rd(bus, node, 0x2026, 0, signed=True)
    print(f"[1] 2026h zero offset: {was} -> {value} mm")
    if not wr(bus, node, 0x2026, 0, value, 2, "zero offset"):
        return 1
    now = rd(bus, node, 0x2026, 0, signed=True)
    print(f"    reads back {now} {OK if now == value else BAD}")
    return 0 if now == value else 1


def teach_zero(bus, node):
    """202Ch. Captures whatever is under the sensor NOW as the new zero."""
    print("[1] pre-flight")
    nlcp = rd(bus, node, 0x2021, 4)
    if nlcp is None:
        print(f"    {BAD} could not read the sensor - aborting.")
        return 1
    if nlcp == 0:
        print(f"    {BAD} no track visible. The zero point teach captures the")
        print("      current line position; with no line there is nothing to")
        print("      teach. Park the AGV on the tape first.")
        return 1
    if nlcp != 2:
        print(f"    {BAD} #LCP {nlcp} - more than one track is visible. The")
        print("      sensor rejects this (red flashing LED). Move clear of the")
        print("      diverter and re-run.")
        return 1
    pos = rd(bus, node, 0x2021, 2, signed=True)
    print(f"    one track at LCP2 {pos:+d} mm")
    print(f"\n    {WARN} this bakes the CURRENT parking position in as zero.")
    print("      It is only correct if the AGV is deliberately centred on the")
    print("      tape right now. If the bracket is off-centre, fix the bracket")
    print("      instead - a taught offset hides it and survives re-mounting.")

    print("\n[2] teach")
    if not wr(bus, node, 0x202C, 0, 1, 1, "teach zero position"):
        return 1
    time.sleep(0.5)
    print("\n[3] verify")
    print(f"    2026h zero offset   {rd(bus, node, 0x2026, 0, signed=True)} mm")
    print(f"    LCP2 now            {rd(bus, node, 0x2021, 2, signed=True):+d} mm"
          f"  (should be near 0)")
    return 0


WRITE_MODES = {"reset-event", "calibrate", "filter", "minlevel", "offset", "zero"}


def main():
    ap = argparse.ArgumentParser(
        description="Tune the SICK MLS magnetic line sensor. Writes need --go.")
    ap.add_argument("mode", nargs="?", default="show",
                    choices=("show", "events", "reset-event", "calibrate",
                             "filter", "minlevel", "offset", "zero"))
    ap.add_argument("value", nargs="?", type=int,
                    help="for filter (0-4), minlevel (digits), offset (mm)")
    ap.add_argument("--node", type=int, default=SENSOR_NODE)
    ap.add_argument("--go", action="store_true",
                    help="required for anything that writes to the sensor")
    args = ap.parse_args()

    needs_value = args.mode in ("filter", "minlevel", "offset")
    if needs_value and args.value is None:
        print(f"{BAD}: `{args.mode}` needs a value, e.g. "
              f"`tune_mls.py {args.mode} 0 --go`")
        return 2

    # Range-check before touching the bus: an out-of-range argument is a typo,
    # and a typo should not need the sensor powered to be told about.
    limits = {"filter": (0, 4, "table 18 defines 0-4"),
              "minlevel": (0, 0xFFFF, "UINT16"),
              "offset": (-32768, 32767, "INT16")}
    if needs_value:
        lo, hi, why = limits[args.mode]
        if not lo <= args.value <= hi:
            print(f"{BAD}: `{args.mode}` must be {lo}..{hi} ({why}); "
                  f"got {args.value}")
            return 2

    if args.mode in WRITE_MODES and not args.go:
        print(f"{WARN}: `{args.mode}` writes to the sensor. Re-run with --go.")
        print("      Nothing has been changed.")
        return 2

    if args.mode in WRITE_MODES:
        print(f"{WARN} the control service must not be running - it owns can0")
        print("      and holds the sensor in Operational.\n")

    try:
        bus, how = open_bus()
    except Exception as e:
        print(f"{BAD}: {e}")
        return 2
    print(f"connected via {how}\n")

    try:
        if args.mode == "show":
            return show(bus, args.node)
        if args.mode == "events":
            return 0 if show_events(bus, args.node,
                                    indent="    ") is not None else 1
        if args.mode == "reset-event":
            return reset_event(bus, args.node)
        if args.mode == "calibrate":
            return calibrate(bus, args.node)
        if args.mode == "filter":
            return set_filter(bus, args.node, args.value)
        if args.mode == "minlevel":
            return set_minlevel(bus, args.node, args.value)
        if args.mode == "offset":
            return set_offset(bus, args.node, args.value)
        if args.mode == "zero":
            return teach_zero(bus, args.node)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    finally:
        bus.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
