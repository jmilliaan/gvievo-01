#!/usr/bin/env python3
"""No-motion session setpoint watch. Read-only. Never sends hb=1.

Records target, nodes[*].rpm, nodes[*].state, armed, mode, dry_run, blind.plan
for the whole session, and flags anything that must stop the session.
"""
import json, sys, time, urllib.request

URL = "http://127.0.0.1:5000/api/state"
OUT = sys.argv[1] if len(sys.argv) > 1 else "statepoll.jsonl"
ALARM = OUT.replace(".jsonl", "-ALARMS.txt")
PERIOD = 0.2
RPM_NOISE = 5.0          # |rpm| at or above this is motion, not reading noise

def alarm(msg, rec):
    line = f"{time.strftime('%H:%M:%S')} ALARM {msg} :: {json.dumps(rec)}"
    with open(ALARM, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)

prev = None
while True:
    t0 = time.time()
    try:
        with urllib.request.urlopen(URL, timeout=2.0) as r:
            s = json.load(r)
    except Exception as e:
        rec = {"t": time.time(), "err": type(e).__name__ + ": " + str(e)[:80]}
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")
        time.sleep(PERIOD)
        continue

    nodes = s.get("nodes") or {}
    blind = s.get("blind")
    rec = {
        "t": round(time.time(), 3),
        "armed": s.get("armed"), "mode": s.get("mode"),
        "dry_run": s.get("dry_run"), "auto_running": s.get("auto_running"),
        "fault": s.get("fault"), "eto_hold": s.get("eto_hold"),
        "auto_hold": s.get("auto_hold"),
        "target": s.get("target"),
        "n1_rpm": (nodes.get("1") or {}).get("rpm"),
        "n2_rpm": (nodes.get("2") or {}).get("rpm"),
        "n1_state": (nodes.get("1") or {}).get("state"),
        "n2_state": (nodes.get("2") or {}).get("state"),
        "n1_zero": (nodes.get("1") or {}).get("speed_zero"),
        "n2_zero": (nodes.get("2") or {}).get("speed_zero"),
        "sensor_age_s": s.get("sensor_age_s"),
        "tag_age_s": (s.get("rfid") or {}).get("tag_age_s"),
        "blind_plan": (blind or {}).get("plan") if isinstance(blind, dict) else None,
        "event_seq": s.get("event_seq"),
        "seq_route": (s.get("route") or {}).get("stage") if isinstance(s.get("route"), dict) else None,
    }
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")

    tgt = rec["target"] or {}
    if (tgt.get("left") or 0) != 0 or (tgt.get("right") or 0) != 0:
        alarm("TARGET LEFT 0/0", rec)
    for k in ("n1_rpm", "n2_rpm"):
        v = rec[k]
        if v is not None and abs(v) >= RPM_NOISE:
            alarm(f"WHEEL RPM {k}={v}", rec)
    if rec["auto_running"] and rec["dry_run"]:
        for k in ("n1_state", "n2_state"):
            if rec[k] == "Operation enabled":
                alarm(f"DRIVE ENABLED IN DRY-RUN AUTO ({k})", rec)

    if prev is not None:
        for k in ("armed", "mode", "dry_run", "auto_running", "fault",
                  "n1_state", "n2_state", "blind_plan", "eto_hold", "auto_hold"):
            if prev.get(k) != rec.get(k):
                print(f"{time.strftime('%H:%M:%S')} {k}: {prev.get(k)!r} -> {rec.get(k)!r}", flush=True)
    prev = rec

    time.sleep(max(0.0, PERIOD - (time.time() - t0)))
