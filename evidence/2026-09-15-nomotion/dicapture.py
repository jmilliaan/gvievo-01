#!/usr/bin/env python3
"""A01 panel-input capture. Read-only, never sends hb=1.

Logs every change in the DIO input bits alongside the motion-relevant state,
so each physical press can be matched to the bit and label it drove.
"""
import json, sys, time, urllib.request

URL = "http://127.0.0.1:5000/api/state"
OUT = sys.argv[1]
prev = None
print("watching DI changes (10 Hz)... press one input at a time", flush=True)
while True:
    t0 = time.time()
    try:
        with urllib.request.urlopen(URL, timeout=2.0) as r:
            s = json.load(r)
    except Exception:
        time.sleep(0.1); continue

    dio = s.get("dio") or {}
    di = dio.get("di") or []
    names = dio.get("di_names") or []
    nodes = s.get("nodes") or {}
    panel = s.get("panel") or {}
    cur = {
        "di": list(di),
        "selector": panel.get("selector"),
        "armed": s.get("armed"), "mode": s.get("mode"),
        "last_action": panel.get("last_action"),
        "starting_in": panel.get("starting_in"),
        "auto_running": s.get("auto_running"),
        "target": s.get("target"),
        "n1": (nodes.get("1") or {}).get("state"),
        "n2": (nodes.get("2") or {}).get("state"),
        "n1_rpm": (nodes.get("1") or {}).get("rpm"),
        "n2_rpm": (nodes.get("2") or {}).get("rpm"),
        "event_seq": s.get("event_seq"),
    }
    if prev is None or cur != prev:
        ts = time.strftime("%H:%M:%S") + ".%02d" % int((time.time() % 1) * 100)
        changed = []
        if prev is not None:
            for i, v in enumerate(cur["di"]):
                if i < len(prev["di"]) and prev["di"][i] != v:
                    label = names[i] if i < len(names) else "?"
                    changed.append(f"DI{i} '{label}' {prev['di'][i]} -> {v}")
            for k in ("selector","armed","mode","last_action","auto_running",
                      "starting_in","n1","n2","event_seq"):
                if prev.get(k) != cur.get(k):
                    changed.append(f"{k}: {prev.get(k)!r} -> {cur.get(k)!r}")
        line = (f"{ts}  " + ("; ".join(changed) if changed else "BASELINE")
                + f"  | target={cur['target']} rpm={cur['n1_rpm']}/{cur['n2_rpm']}")
        print(line, flush=True)
        with open(OUT, "a") as f:
            f.write(json.dumps({"ts": ts, "changed": changed, **cur}) + "\n")
        prev = cur
    time.sleep(max(0.0, 0.1 - (time.time() - t0)))
