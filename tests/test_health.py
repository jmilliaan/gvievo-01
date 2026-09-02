"""Hardware liveness: the two-tier watchdog table."""
import math
import os
import pathlib
import struct
import sys
import threading

from helpers import FAIL, ROOT, check, sensor

import autopilot
import config
import kinematics
import motion

def test_health():
    """Hardware liveness: the two-tier watchdog and its edge reporting.

    The hole this closes: _poll_telemetry() keeps the last statusword when an
    SDO read returns None, so before health.py a driver that stopped answering
    looked alive for as long as the process ran.
    """
    import health
    print("\nhardware health")

    # -- a source is not a fault until it has been seen once -----------------
    src = health.HealthSource("mls")
    mon = health.HealthMonitor([(src, 1.0)])
    r = mon.evaluate(now=100.0)
    check("a never-seen source is not reported lost",
          not r["sensor_error"] and not r["system_error"])
    check("a never-seen source reports seen=False",
          r["sources"]["mls"]["seen"] is False)

    src.mark_rx(now=100.0)
    r = mon.evaluate(now=100.5)
    check("a fresh source is healthy", r["sources"]["mls"]["ok"] is True)
    r = mon.evaluate(now=101.5)
    check("a source past its timeout is lost", r["sensor_error"] is True,
          r["sensor_detail"])
    src.mark_rx(now=101.6)
    r = mon.evaluate(now=101.7)
    check("a source recovers on the next read", r["sensor_error"] is False)

    # -- the two tiers route differently -------------------------------------
    drv = health.HealthSource("driver:1", critical=True, detail="node 1 (left)")
    mls = health.HealthSource("mls")
    mon = health.HealthMonitor([(drv, 0.5), (mls, 0.5)])
    drv.mark_rx(now=0.0)
    mls.mark_rx(now=0.0)
    mon.evaluate(now=0.1)
    mls.mark_rx(now=1.0)                 # sensor alive, driver silent
    r = mon.evaluate(now=1.0)
    check("a silent driver raises the CRITICAL tier",
          r["system_error"] is True and r["sensor_error"] is False,
          r["system_detail"])
    drv.mark_rx(now=2.0)                 # driver back, sensor now silent
    r = mon.evaluate(now=2.0)
    check("a silent sensor raises the AUTO-ONLY tier",
          r["sensor_error"] is True and r["system_error"] is False,
          r["sensor_detail"])

    # -- edges fire ONCE, not once per tick ----------------------------------
    # This is the events.py trap: at 50 Hz a per-tick emit empties the whole
    # 200-entry ring in about four seconds.
    s = health.HealthSource("x", critical=True)
    mon = health.HealthMonitor([(s, 0.5)])
    s.mark_rx(now=0.0)
    mon.evaluate(now=0.0)
    edges = tier_edges = 0
    for i in range(100):                 # 2 s of ticks with the source dead
        r = mon.evaluate(now=1.0 + i * 0.02)
        edges += len(r["changed"])
        tier_edges += r["system_edge"] is not None
    check("a source transition is reported once, not per tick", edges == 1,
          f"{edges} edge(s) over 100 ticks")
    check("a tier transition is reported once, not per tick", tier_edges == 1,
          f"{tier_edges} edge(s) over 100 ticks")

    # -- PullSource wraps an existing snapshot -------------------------------
    snap = {"comms_ok": True, "rx_age_s": 0.2, "detail": "reader"}
    pull = health.PullSource("rfid", lambda: snap)
    mon = health.HealthMonitor([(pull, 5.0)])
    check("a pull source reports its snapshot verdict",
          mon.evaluate(now=0.0)["sources"]["rfid"]["ok"] is True)
    snap["comms_ok"] = False
    check("a pull source fault reaches the auto-only tier",
          mon.evaluate(now=0.0)["sensor_error"] is True)
    # rfid.enabled false -> comms_ok is None -> not in use, never a fault.
    snap["comms_ok"] = None
    r = mon.evaluate(now=0.0)
    check("a disabled pull source never blocks a mode",
          r["sensor_error"] is False and r["sources"]["rfid"]["in_use"] is False)
    pull_raises = health.PullSource("boom", lambda: 1 / 0)
    check("a raising snapshot is absorbed, never propagated",
          health.HealthMonitor([(pull_raises, 1.0)]).evaluate(now=0.0)
          ["sensor_error"] is False)

    # -- reset clears history across a bus reopen ----------------------------
    s = health.HealthSource("y")
    s.mark_rx(now=0.0)
    mon = health.HealthMonitor([(s, 0.5)])
    mon.reset()
    check("reset() forgets a stale timestamp",
          mon.evaluate(now=999.0)["sensor_error"] is False)

    # -- health.py stays dependency-free -------------------------------------
    head = (ROOT / "core" / "health.py").read_text()
    head = head[head.index('"""', head.index('"""') + 3):]
    imports = {ln.split()[1].split(".")[0] for ln in head.splitlines()
               if ln.startswith(("import ", "from "))}
    check("health.py imports only the standard library",
          imports <= {"time"}, str(sorted(imports)))

    # -- wired into the vehicle, on the paths that prove liveness ------------
    cw = (ROOT / "canworker.py").read_text()
    check("the sensor marks health on every decoded frame",
          "self._src_mls.mark_rx(" in cw)
    check("each driver marks health on a telemetry answer",
          "self._src_node[nid].mark_rx()" in cw)
    check("health is evaluated outside the lock",
          "hw = self._hw.evaluate(now)" in cw)
    check("a critical fault refuses an arm", "system_error" in
          cw[cw.index("def _do_arm"):cw.index("def _do_disarm")])


TESTS = [
    test_health,
]
