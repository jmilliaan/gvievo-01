"""The web tier: the watchdog opt-in and the read-only monitor page."""
import math
import os
import pathlib
import struct
import sys
import threading

from helpers import FAIL, ROOT, check

import autopilot
import config
import kinematics
import motion

def test_monitor_page_does_not_feed_the_watchdog():
    """A read-only page must not hold an auto run alive.

    /api/state used to call keepalive() unconditionally, so ANY page polling it
    fed the auto watchdog - meaning a monitoring page open on a second screen
    would keep a run going after the auto page had been closed. The heartbeat is
    now opt-in, and forgetting the flag stops the run rather than extending it.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe monitoring page cannot hold a run alive")

    seen = []
    real = webapp.ctl.keepalive
    webapp.ctl.keepalive = lambda: seen.append(1)
    try:
        c = webapp.app.test_client()
        c.get("/api/state")
        check("/api/state alone does NOT refresh the watchdog", not seen,
              f"{len(seen)} refresh(es)")
        c.get("/api/can")
        check("/api/can does NOT refresh the watchdog", not seen)
        c.get("/api/state?hb=1")
        check("/api/state?hb=1 DOES refresh the watchdog", len(seen) == 1)
    finally:
        webapp.ctl.keepalive = real

    # Only the page that drives the vehicle may claim it.
    auto = (ROOT / "app" / "templates" / "auto.html").read_text()
    mon = (ROOT / "app" / "templates" / "monitor.html").read_text()
    common = (ROOT / "app" / "static" / "common.js").read_text()
    check("the auto page claims the heartbeat", "CLAIM_HEARTBEAT = true" in auto)
    check("the monitor page does not", "CLAIM_HEARTBEAT" not in mon)
    check("the claim is declared before common.js polls",
          "prescript" in auto and "prescript" in
          (ROOT / "app" / "templates" / "base.html").read_text())
    check("common.js only sends hb=1 when the page claims it",
          "CLAIM_HEARTBEAT ? '/api/state?hb=1'" in common)

    # The page itself must render and be read-only.
    c = webapp.app.test_client()
    body = c.get("/monitor").get_data(as_text=True)
    check("the monitor page renders", "Diagnostic only" in body)
    check("it states the golden rule", "not a safety path" in body)
    check("it publishes the write deny-list", "403Eh" in body and "40D0h" in body)
    check("it has no controls", "<button" not in body)


TESTS = [
    test_monitor_page_does_not_feed_the_watchdog,
]
