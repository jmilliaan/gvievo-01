"""Wi-Fi link quality for the header indicator.

*** NOT a safety function, and not a health source. *** Nothing here can stop,
arm or gate the vehicle, and it is deliberately not registered with health.py:
a weak link is already covered by the thing that actually matters, which is the
MANUAL_WATCHDOG_S deadline in canworker. If the browser stops re-POSTing, the
setpoint is zeroed whatever the reason - a bad link, a closed tab, a flat
laptop battery. This module only explains to the operator WHY that is about to
happen, before it does.

That distinction is the reason it reads and reports rather than judging. It
says how strong the link is; canworker decides what silence means.

WHY /proc AND NOTHING ELSE
--------------------------
/proc/net/wireless is a two-line text read with no dependency, no capability
and no syscall that can block. `iw dev ... link` and the netlink socket both
give more (SSID, bitrate, the AP's MAC), and both cost a subprocess or a
library on a machine whose control loop runs at 50 Hz. The bars want one
number; this is the cheapest place that has it.

READ ON THE FLASK THREAD, NOT THE BUS THREAD
--------------------------------------------
server.py merges snapshot() into /api/state. The bus thread never calls this,
so a stat() that goes slow on a loaded machine cannot land in a tick. The
cache below exists for the other direction: /api/state is polled at 5 Hz by
every open page, and re-reading the file for each of them is pointless when
the value moves on a human timescale.

WHAT THE COLUMNS MEAN
---------------------
    wlp1s0: 0000   70.  -39.  -256   ...
              |     |     |     |
              |     |     |     noise floor, dBm (-256 = not reported)
              |     |     signal level, dBm - the number the bars are drawn from
              |     link quality, driver-defined scale (usually 0..70)
              interface status

`level` is what an operator recognises: -39 dBm is excellent, -80 dBm is the
edge of usable. Quality is driver-defined and not comparable between adapters,
so it travels for reference but the bars are never derived from it.
"""
import os
import time

PROC = "/proc/net/wireless"

# dBm -> bars. The boundaries are the usual ones for 2.4/5 GHz: -67 dBm is the
# accepted floor for reliable voice/video, so two bars is the point at which a
# held jog button is worth worrying about, and one bar is already marginal.
_BARS = ((-55, 4), (-65, 3), (-72, 2), (-80, 1))
MAX_BARS = 4

# A link at or below this gets coloured in the header. Not a threshold anything
# ACTS on - see the module docstring.
WEAK_BARS = 2

_CACHE_S = 1.0
_cache = {"t": 0.0, "snap": None}


def bars_for(dbm):
    """dBm -> 0..4. None (not associated, or no radio) is zero bars."""
    if dbm is None:
        return 0
    for floor, bars in _BARS:
        if dbm >= floor:
            return bars
    return 0


def _parse(text):
    """The two header lines, then one row per interface. Never raises."""
    out = []
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        if not rest:
            continue
        cols = rest.split()
        if len(cols) < 3:
            continue
        try:
            # Trailing dots mark a value the driver flagged as updated; they
            # are not decimal points, and float() would silently accept "70."
            # as 70.0 either way. Strip so the intent is on the page.
            quality = float(cols[1].rstrip("."))
            level = float(cols[2].rstrip("."))
        except ValueError:
            continue
        # An associated card reports a negative dBm. 0 is what an idle or
        # down interface reports, and drawing four bars for it would be the
        # one genuinely misleading thing this module could do.
        out.append({"iface": name.strip(),
                    "quality": quality,
                    "dbm": level if level < 0 else None})
    return out


def snapshot(now=None):
    """{present, iface, dbm, bars, quality, weak}. Cached ~1 s. Never raises.

    present=False means there is no wireless interface at all - a vehicle on a
    cable, or a kernel without the module. The indicator hides entirely rather
    than showing zero bars, which would read as "connected, no signal".
    """
    now = time.monotonic() if now is None else now
    if _cache["snap"] is not None and now - _cache["t"] < _CACHE_S:
        return _cache["snap"]

    try:
        with open(PROC) as fh:
            rows = _parse(fh.read())
    except OSError:                     # noqa: BLE001 - no radio, no indicator
        rows = []

    if not rows:
        snap = {"present": False, "iface": None, "dbm": None, "bars": 0,
                "quality": None, "weak": False}
    else:
        # Strongest associated interface, so a second idle radio cannot mask a
        # good link. max() over a None-free key; unassociated sort to the back.
        row = max(rows, key=lambda r: (r["dbm"] is not None,
                                       r["dbm"] if r["dbm"] is not None else -999))
        bars = bars_for(row["dbm"])
        snap = {"present": True, "iface": row["iface"], "dbm": row["dbm"],
                "bars": bars, "quality": row["quality"],
                # Associated but faint, or associated and then dropped. Both
                # are worth colouring; neither is worth acting on here.
                "weak": bars <= WEAK_BARS}
    _cache.update(t=now, snap=snap)
    return snap


def reset():
    """Forget the cached read. Tests only."""
    _cache.update(t=0.0, snap=None)
