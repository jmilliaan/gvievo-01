#!/usr/bin/env python3
"""Read the SICK MLS magnetic line sensor on can0. Read-only - nothing moves.

Restored 2026-09-19 from 8403dcb^ for line following as an engineering feature
(manuals/slam-generalized-plan/line-follow-u11-layout-plan.md §1.1). The ROS
side (amr_base/mls_track.py, inside drive_node) imports the decoders below; the
CLI is for the bench and refuses to run while drive_node owns the bus.

The sensor is node 10 at 125 kbps. Two ways to get measurements out of it:

  snapshot  one-shot SDO read of the whole picture (identity, config, live
            values). Works in Pre-operational, so it needs no state change.
  poll      snapshot's live values on a loop, via SDO. Slow (~3 ms/read) but
            leaves the bus in Pre-operational.
  stream    decode TPDO1 at 10 ms. TPDOs only flow in Operational. With --nmt
            this sends NMT Start addressed to node 10 only and puts it back to
            Pre-operational on exit; without it, it only listens.
  calibrate two-step field survey, still read-only: --step background with the
            sensor over bare floor, then --step tape with it centred over the
            tape. Each step samples by SDO and saves to ~/.amr/mls_cal/; once
            both exist it prints the comparison and a suggested 2025h min.
            level and the measured zero offset. It suggests, never writes:
            the sensor's parameters stay a deliberate, separate act.

TPDO1 (COB-ID 0x180+NodeID, SICK MLS operating instructions 8021642 table 6):

  byte 0-1  LCP1   INT16, mm      byte 6  bits 0-2 #LCP, bits 3-7 marker
  byte 2-3  LCP2   INT16, mm      byte 7  status bits (table 8)
  byte 4-5  LCP3   INT16, mm

LCP2 is the one that matters for line following: per table 17 the sensor always
populates LCP2 first, so with a single tape under the sensor LCP2 is the track
position and LCP1/LCP3 are meaningless. Only on a diverter do the others fill in.

Position sign follows the cable outlet unless 2027h (sensor flipped) is set.

*** LCP layout depends on 2006h:01 (Variant TPDO1). ***
Values 1/5/6/7 select "Combi", which repacks each 16-bit field as a 10-bit
signed position plus a 6-bit track width. This script reads 2006h:01 and
decodes accordingly rather than assuming. This unit ships set to 3 (Standard
enhanced), i.e. plain INT16.

*** Commissioned to 0 (Standard), NOT the factory 3. *** The "enhanced" values
are the improved diverter detection, and p.49 table 21 / p.50 recommend that
ON for FLUSH diverters and OFF for NON-FLUSH ones - a separate tape running
parallel to the main track and then curving away, which is how this route is
laid. Both 0 and 3 are Standard packing, so the decode below is the same
either way; what changes is how the sensor behaves where two tapes are in the
window at once.

Deliberately free of `config`, like the rest of canbus/.
"""
import argparse
import json
import os
import statistics
import struct
import sys
import time

import can  # noqa: E402

from agv_core.drivers.canbus.verify_drivers import BAD, OK, WARN, open_bus, sdo_read  # noqa: E402

SENSOR_NODE = 10
TPDO1_COB = 0x180
TPDO1_COMM = 0x1800           # :01 COB-ID (bit 31 = disabled), :02 type, :05 event timer
OBJ_VARIANT = (0x2006, 1)
OBJ_LCP = 0x2021              # :01..:03 LCP1..3, :04 #LCP (+marker), :0B..:0D line levels
OBJ_NLCP = (0x2021, 4)
OBJ_STATUS = (0x2022, 0)
COB_DISABLED = 1 << 31

# 2006h:01 - which of these select the packed Combi track-data format (table 10).
COMBI_VARIANTS = {1, 5, 6, 7}
VARIANT_NAMES = {
    0: "Standard", 1: "Combi",
    2: "Standard compensated", 3: "Standard enhanced",
    4: "Standard enhanced compensated", 5: "Combi compensated",
    6: "Combi enhanced", 7: "Combi enhanced compensated",
}

# byte 6 bits 0-2. Table 7 labels both 3 and 6 "Left diverter", which cannot be
# right; table 17 only says "single diverter" for each. Report which LCPs are
# valid instead of guessing a handedness the manual contradicts itself on.
NLCP_MEANING = {
    0: ("no track", ()),
    2: ("one track", (2,)),
    3: ("diverter, LCP1+LCP2", (1, 2)),
    6: ("diverter, LCP2+LCP3", (2, 3)),
    7: ("three tracks / 90 deg intersection", (1, 2, 3)),
}

FIELD_LEVEL_MT = 0.00076   # 2024h resolution, manual p.43
LINE_LEVEL_MT = 0.049      # 2021h:0B..0D resolution, manual p.43


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def decode_lcp(word, combi):
    """One 16-bit track field -> (position_mm, width_mm or None)."""
    if not combi:
        return s16(word), None
    # LSB = LCP bits 0-7; MSB bit 0 = LCP bit 8, bits 1-6 = width, bit 7 = LCP bit 9.
    lsb, msb = word & 0xFF, word >> 8
    pos = lsb | ((msb & 0x01) << 8) | ((msb >> 7) << 9)
    if pos & 0x200:                      # 10-bit two's complement
        pos -= 0x400
    return pos, (msb >> 1) & 0x3F


def decode_status(b):
    return {
        "line_good": bool(b & 0x01),
        "track_level": (b >> 1) & 0x07,   # 0-7, see manual table 19
        "sensor_flipped": bool(b & 0x10),
        "polarity": "south" if b & 0x20 else "north",
        "reading_code": bool(b & 0x40),
        "event_flag": bool(b & 0x80),
    }


def decode_marker(b):
    """byte 6 bits 3-7: bit 3 is the introductory character, bits 4-7 the code."""
    return {"intro": bool(b & 0x08), "code": (b >> 4) & 0x0F}


def decode_tpdo1(data, combi):
    if len(data) < 8:
        return None
    w = struct.unpack_from("<HHH", data, 0)
    lcps = [decode_lcp(x, combi) for x in w]
    nlcp = data[6] & 0x07
    label, valid = NLCP_MEANING.get(nlcp, (f"reserved ({nlcp})", ()))
    return {
        "lcp": lcps, "nlcp": nlcp, "nlcp_label": label, "valid": valid,
        "marker": decode_marker(data[6]), "status": decode_status(data[7]),
    }


def decode_sdo(words, nlcp, status, combi):
    """The TPDO1 fields read one by one over SDO (2021h:01..04, 2022h) -> the
    same dict decode_tpdo1 returns, by packing them into a TPDO1 frame."""
    data = struct.pack("<HHHBB", *(w & 0xFFFF for w in words), nlcp & 0xFF, status & 0xFF)
    return decode_tpdo1(data, combi)


def fmt_reading(r):
    """One line: the track position, then the qualifiers that explain it."""
    st = r["status"]
    if r["valid"]:
        parts = []
        for i in r["valid"]:
            pos, width = r["lcp"][i - 1]
            parts.append(f"LCP{i} {pos:>+5} mm" + (f" (w {width:>2})" if width is not None else ""))
        track = "  ".join(parts)
    else:
        track = "-- no track --"
    flags = []
    if st["reading_code"]:
        flags.append("reading code")
    if r["marker"]["intro"] or r["marker"]["code"]:
        flags.append(f"marker {r['marker']['code']}")
    if st["event_flag"]:
        flags.append(f"{WARN} event flag")
    if st["sensor_flipped"]:
        flags.append("flipped")
    # With no tape under the sensor, line_good = 0 is the resting state, not a
    # fault. It is only worth flagging when a track IS detected but too weak.
    if not r["valid"]:
        good = "  --"
    else:
        good = OK if st["line_good"] else f"{BAD} weak"
    return (f"{track:<44} {good} lvl {st['track_level']} "
            f"{st['polarity']:<5} " + " ".join(flags)).rstrip()


# --- SDO path ---------------------------------------------------------------

def rd(bus, node, index, sub, signed=False):
    st, val, _, _ = sdo_read(bus, node, index, sub)
    if not st:
        return None
    n = len(val)
    return int.from_bytes(val, "little", signed=signed) if n else None


def read_variant(bus, node):
    """2006h:01. Returns (raw, is_combi). Assumes Standard if unreadable."""
    v = rd(bus, node, *OBJ_VARIANT)
    if v is None:
        print(f"    {WARN} could not read 2006h:01 - assuming Standard (plain INT16)")
        return None, False
    return v, v in COMBI_VARIANTS


def live_values(bus, node, combi):
    """The same fields TPDO1 carries, but via SDO so it works Pre-operational."""
    words = [rd(bus, node, OBJ_LCP, s) for s in (1, 2, 3)]
    if any(w is None for w in words):
        return None
    nlcp = rd(bus, node, *OBJ_NLCP)
    status = rd(bus, node, *OBJ_STATUS)
    if nlcp is None or status is None:
        return None
    return decode_sdo(words, nlcp, status, combi)


def snapshot(bus, node):
    print(f"[1] identity (node {node})")
    order = rd(bus, node, 0x2019, 0)
    if order is None:
        print(f"    {BAD} node {node} did not answer 2019h - is the sensor powered?")
        return 1
    print(f"    order number   {order}")
    for sub, name in ((1, "vendor ID"), (2, "product code"),
                      (3, "revision"), (4, "serial number")):
        v = rd(bus, node, 0x1018, sub)
        if v is not None:
            print(f"    {name:<14} 0x{v:08X}")

    print("\n[2] configuration")
    variant, combi = read_variant(bus, node)
    if variant is not None:
        name = VARIANT_NAMES.get(variant, "?")
        print(f"    2006h:01 variant TPDO1   {variant} ({name}) "
              f"-> track data {'Combi (packed)' if combi else 'Standard (INT16)'}")
    for index, sub, label, signed, unit in (
        (0x2025, 0, "2025h min. level", False, "digits"),
        (0x2026, 0, "2026h zero offset", True, "mm"),
        (0x2027, 0, "2027h sensor flipped", False, ""),
        (0x2028, 1, "2028h:01 use markers", False, ""),
        (0x2028, 2, "2028h:02 marker style", False, ""),
    ):
        v = rd(bus, node, index, sub, signed)
        if v is not None:
            print(f"    {label:<24} {v}{' ' + unit if unit else ''}")
    cob = rd(bus, node, TPDO1_COMM, 1)
    ttype = rd(bus, node, TPDO1_COMM, 2)
    timer = rd(bus, node, TPDO1_COMM, 5)
    if cob is not None:
        state = f"{BAD} DISABLED" if cob & COB_DISABLED else f"{OK} enabled"
        print(f"    1800h TPDO1              COB-ID 0x{cob & 0x7FF:03X} {state}, "
              f"type 0x{ttype or 0:02X}, event timer {timer} ms")

    print("\n[3] live measurement")
    field = rd(bus, node, 0x2024, 0)
    minlvl = rd(bus, node, 0x2025, 0)
    if field is not None:
        note = ""
        if minlvl is not None and field < minlvl:
            note = f"   <-- below min. level {minlvl}, no track will be reported"
        print(f"    2024h field level        {field} "
              f"({field * FIELD_LEVEL_MT:.2f} mT){note}")
    for sub, i in ((0x0B, 1), (0x0C, 2), (0x0D, 3)):
        v = rd(bus, node, OBJ_LCP, sub, signed=True)
        if v is not None:
            print(f"    2021h:{sub:02X} line level {i}     {v:>+4} "
                  f"({v * LINE_LEVEL_MT:+.2f} mT)")
    r = live_values(bus, node, combi)
    if r is None:
        print(f"    {BAD} could not read the track objects")
        return 1
    print(f"\n    #LCP {r['nlcp']} - {r['nlcp_label']}")
    print(f"    {fmt_reading(r)}")
    return 0


def poll(bus, node, seconds, interval):
    variant, combi = read_variant(bus, node)
    print(f"polling node {node} by SDO for {seconds:.0f} s "
          f"({'Combi' if combi else 'Standard'} track data). Ctrl-C to stop.\n")
    t_end = time.time() + seconds
    while time.time() < t_end:
        r = live_values(bus, node, combi)
        print(f"    {fmt_reading(r) if r else BAD + ' no response'}")
        time.sleep(interval)
    return 0


# --- calibrate: background vs tape ----------------------------------------

CAL_DIR = os.path.expanduser("~/.amr/mls_cal")
CAL_STEPS = ("background", "tape")
# A tape step must see one track this often, and its weakest field must clear the
# strongest background by this ratio. Engineering margins, not SICK figures.
CAL_DETECT_MIN = 0.95
CAL_RATIO_MIN = 2.0


def cal_sample(bus, node, combi):
    """One SDO sample of everything the comparison needs, or None."""
    r = live_values(bus, node, combi)
    field = rd(bus, node, 0x2024, 0)
    if r is None or field is None:
        return None
    levels = [rd(bus, node, OBJ_LCP, sub, signed=True) for sub in (0x0B, 0x0C, 0x0D)]
    return {
        "field": field,
        "line_levels": levels,
        "nlcp": r["nlcp"],
        "lcp_mm": [pos for pos, _ in r["lcp"]],
        "valid": list(r["valid"]),
        "line_good": r["status"]["line_good"],
        "track_level": r["status"]["track_level"],
        "polarity": r["status"]["polarity"],
    }


def cal_record(bus, node, step, samples, interval):
    """Sample one step and save it with the sensor's current settings."""
    variant, combi = read_variant(bus, node)
    settings = {
        "min_level_2025h": rd(bus, node, 0x2025, 0),
        "zero_offset_mm_2026h": rd(bus, node, 0x2026, 0, signed=True),
        "flipped_2027h": rd(bus, node, 0x2027, 0),
        "variant_2006h": variant,
    }
    print(f"[{step}] sampling {samples}x by SDO, every {interval:.2f} s - keep the vehicle still")
    got, missed = [], 0
    for _ in range(samples):
        x = cal_sample(bus, node, combi)
        if x is None:
            missed += 1
        else:
            got.append(x)
        time.sleep(interval)
    if not got:
        print(f"    {BAD} no response from node {node}")
        return None
    rec = {"step": step, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "node": node,
           "settings": settings, "missed": missed, "samples": got}
    os.makedirs(CAL_DIR, exist_ok=True)
    path = os.path.join(CAL_DIR, f"{step}.json")
    with open(path, "w") as f:
        json.dump(rec, f, indent=1)
    print(f"    {OK} {len(got)} samples ({missed} missed) -> {path}")
    return rec


def _stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"min": min(xs), "max": max(xs), "mean": round(statistics.fmean(xs), 2),
            "sd": round(statistics.pstdev(xs), 2)}


def cal_summary(bg, tape):
    """Compare a background and a tape record. Pure: the tests feed it dicts."""
    b, t = bg["samples"], tape["samples"]
    bf, tf = _stats([s["field"] for s in b]), _stats([s["field"] for s in t])
    lcp2 = _stats([s["lcp_mm"][1] for s in t if 2 in s["valid"]])
    out = {
        "background": {
            "field": bf,
            "line_level_max": max((abs(v) for s in b for v in s["line_levels"] if v is not None), default=None),
            "false_track_rate": round(sum(s["nlcp"] != 0 for s in b) / len(b), 3),
        },
        "tape": {
            "field": tf,
            "line_level_max": max((abs(v) for s in t for v in s["line_levels"] if v is not None), default=None),
            "one_track_rate": round(sum(s["nlcp"] == 2 for s in t) / len(t), 3),
            "line_good_rate": round(sum(s["line_good"] for s in t) / len(t), 3),
            "track_level": _stats([s["track_level"] for s in t]),
            "lcp2_mm": lcp2,
            "polarity": sorted({s["polarity"] for s in t if s["nlcp"]}),
        },
        "settings": tape["settings"],
    }
    ratio = (tf["min"] / bf["max"]) if bf["max"] > 0 else None
    out["ratio_tape_min_to_background_max"] = None if ratio is None else round(ratio, 2)
    # Midway between the strongest background and the weakest tape reading. Only
    # meaningful when the two do not overlap.
    out["suggested_min_level_2025h"] = (round((bf["max"] + tf["min"]) / 2)
                                        if tf["min"] > bf["max"] else None)
    problems = []
    if out["background"]["false_track_rate"] > 0:
        problems.append("a track was reported over bare floor (steel, rebar or a magnet nearby?)")
    if out["tape"]["one_track_rate"] < CAL_DETECT_MIN:
        problems.append(f"one track seen in only {out['tape']['one_track_rate']:.0%} of tape samples")
    if out["suggested_min_level_2025h"] is None:
        problems.append("tape and background field levels overlap")
    elif ratio is not None and ratio < CAL_RATIO_MIN:
        problems.append(f"tape/background ratio {ratio:.2f} below {CAL_RATIO_MIN}")
    if len(out["tape"]["polarity"]) > 1:
        problems.append("polarity changed during the tape step")
    out["problems"] = problems
    out["verdict"] = "OK" if not problems else "CHECK"
    return out


def cal_print(s):
    bf, tf, st = s["background"]["field"], s["tape"]["field"], s["settings"]
    mt = lambda v: f"{v} ({v * FIELD_LEVEL_MT:.2f} mT)"
    print("\n[report] 2024h field level, digits")
    print(f"    background  min {bf['min']}  mean {bf['mean']}  max {mt(bf['max'])}")
    print(f"    tape        min {mt(tf['min'])}  mean {tf['mean']}  max {tf['max']}")
    print(f"    ratio tape min / background max   {s['ratio_tape_min_to_background_max']}")
    print(f"    line level |max|  background {s['background']['line_level_max']}  "
          f"tape {s['tape']['line_level_max']}  (x{LINE_LEVEL_MT} mT)")
    t = s["tape"]
    print(f"    tape: one track {t['one_track_rate']:.0%}, line_good {t['line_good_rate']:.0%}, "
          f"track level {t['track_level']['mean'] if t['track_level'] else '-'}/7, "
          f"polarity {'/'.join(t['polarity']) or '-'}")
    print(f"    background: false track {s['background']['false_track_rate']:.0%}")
    print("\n[report] settings")
    sug = s["suggested_min_level_2025h"]
    print(f"    2025h min. level   now {st['min_level_2025h']}   suggested {sug if sug is not None else '-'}"
          "   (midway; not written)")
    lcp2 = t["lcp2_mm"]
    if lcp2:
        print(f"    LCP2 over the tape {lcp2['mean']:+.1f} mm (sd {lcp2['sd']})   "
              f"2026h zero offset now {st['zero_offset_mm_2026h']} mm")
        print("      if the tape was centred under the sensor, that LCP2 is the mounting offset")
    print(f"\n    verdict: {OK if s['verdict'] == 'OK' else WARN + ' CHECK'}")
    for p in s["problems"]:
        print(f"      - {p}")


def cal_load(step):
    try:
        with open(os.path.join(CAL_DIR, f"{step}.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def calibrate(bus, node, step, samples, interval):
    """--step background | tape | both (prompts between) | report (no bus)."""
    steps = CAL_STEPS if step == "both" else (() if step == "report" else (step,))
    for i, st in enumerate(steps):
        if step == "both":
            where = "bare floor, no tape within 0.5 m" if st == "background" else "centred over the tape"
            input(f"\n{'' if i == 0 else 'Move the vehicle. '}Put the sensor {where}, then press Enter ")
        if cal_record(bus, node, st, samples, interval) is None:
            return 1
    bg, tape = cal_load("background"), cal_load("tape")
    if not bg or not tape:
        print(f"\n    next: --step {'tape' if bg else 'background'} (have: "
              f"{', '.join(k for k, v in (('background', bg), ('tape', tape)) if v) or 'none'})")
        return 0
    s = cal_summary(bg, tape)
    cal_print(s)
    path = os.path.join(CAL_DIR, f"report-{time.strftime('%Y%m%d-%H%M%S')}.json")
    with open(path, "w") as f:
        json.dump(s, f, indent=1)
    print(f"\n    saved {path}")
    return 0 if s["verdict"] == "OK" else 1


# --- PDO path ---------------------------------------------------------------

def nmt(bus, command, node):
    bus.send(can.Message(arbitration_id=0x000, data=[command, node],
                         is_extended_id=False))
    time.sleep(0.05)


def stream(bus, node, seconds, start_nmt):
    variant, combi = read_variant(bus, node)
    cob = TPDO1_COB + node

    if start_nmt:
        print(f"[nmt] Start Remote Node -> node {node} only (not a broadcast, so "
              f"the drivers stay in Pre-operational)")
        nmt(bus, 0x01, node)

    print(f"listening for TPDO1 on 0x{cob:03X} for {seconds:.0f} s "
          f"({'Combi' if combi else 'Standard'} track data). Ctrl-C to stop.\n")
    n, t_end = 0, time.time() + seconds
    last = 0.0
    while time.time() < t_end:
        m = bus.recv(timeout=max(0.0, t_end - time.time()))
        if m is None:
            break
        if m.arbitration_id != cob:
            continue
        n += 1
        r = decode_tpdo1(bytes(m.data), combi)
        if r is None:
            continue
        now = time.time()
        # 10 ms of frames is far more than anyone can read - throttle to 10 Hz.
        if now - last >= 0.1:
            print(f"    {fmt_reading(r)}")
            last = now

    if n == 0:
        print(f"    {BAD} no TPDO1 seen on 0x{cob:03X}.")
        print("      The sensor only transmits PDOs in Operational. Without --nmt it")
        print("      was probably still in Pre-operational.")
        print("      Also check 1800h:01 has not been disabled (MSB set).")
        return 1
    print(f"\n    {OK}: {n} TPDO1 frames in {seconds:.0f} s "
          f"({n / seconds:.0f}/s; 1800h:05 event timer sets the rate)")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Read the SICK MLS magnetic line sensor (read-only).")
    ap.add_argument("mode", nargs="?", default="snapshot",
                    choices=("snapshot", "poll", "stream", "calibrate"))
    ap.add_argument("--node", type=int, default=SENSOR_NODE)
    ap.add_argument("--seconds", type=float, default=10.0,
                    help="duration for poll/stream (default 10)")
    ap.add_argument("--interval", type=float, default=0.2,
                    help="poll period in seconds (default 0.2)")
    ap.add_argument("--nmt", action="store_true",
                    help="stream: send NMT Start to this node first (and Pre-operational on exit)")
    ap.add_argument("--step", default="both", choices=("both",) + CAL_STEPS + ("report",),
                    help="calibrate: which step (default both, with a prompt between)")
    ap.add_argument("--samples", type=int, default=40, help="calibrate: samples per step (default 40)")
    args = ap.parse_args()

    if args.mode == "calibrate" and args.step == "report":
        return calibrate(None, args.node, "report", 0, 0.0)
    if args.mode == "calibrate":
        # SDO answers come back on one COB-ID: a second client on node 10 (drive_node's
        # IMU poll) would read the other's replies. Take the bus owner lock first.
        from agv_core import ownerlock  # noqa: PLC0415
        try:
            lock = ownerlock.acquire("can")  # noqa: F841 - held until exit
        except ownerlock.OwnerBusy as e:
            print(f"{BAD}: can0 is owned ({e}). Stop it first: sudo systemctl stop amr.service")
            return 2

    try:
        bus, how = open_bus()
    except Exception as e:
        print(f"{BAD}: {e}")
        return 2
    print(f"connected via {how}\n")

    try:
        if args.mode == "snapshot":
            return snapshot(bus, args.node)
        if args.mode == "poll":
            return poll(bus, args.node, args.seconds, args.interval)
        if args.mode == "calibrate":
            return calibrate(bus, args.node, args.step, args.samples, args.interval)
        return stream(bus, args.node, args.seconds, args.nmt)
    except KeyboardInterrupt:
        print("\n    interrupted")
        return 1
    finally:
        if args.mode == "stream" and args.nmt:
            # Leave the bus as we found it: PDO traffic off.
            try:
                nmt(bus, 0x80, args.node)
                print(f"[nmt] node {args.node} -> Pre-operational")
            except Exception:
                pass
        bus.shutdown()


if __name__ == "__main__":
    sys.exit(main())
