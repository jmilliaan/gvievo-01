"""The whole run on disk (2026-11-06): every control tick, AMCL pose, readiness change, event and
fork of one line run, from the Start to its end, as gzip JSON lines in <state_dir>/logs/trip_log.

The flight recorder keeps 15 s around a moment. That lost the one fork that mattered: J-SPLIT took
the wrong lane 39 s before the next dump. This keeps all of it, about 2 KB/s.

The control loop only hands a dict to a queue (add() never blocks and never raises). A daemon thread
formats, compresses and writes, so a slow or full disk costs log rows, never a tick. Behind by
queue_size rows, the high-rate rows (tick, amcl, ready) are dropped and counted; the rare ones and
the file's open and close always go in. It flushes every FLUSH_S, so a killed node leaves a readable
file up to that moment.

Rows carry "k": head, route, tick, amcl, ready, event, fork, end. tools/trip_report.py reads them.
"""
from __future__ import annotations

import gzip
import json
import os
import queue
import threading
import time

from agv_core import fsutil

FLUSH_S = 2.0
DROPPABLE = ("tick", "amcl", "ready")
_STOP = object()


class TripLog:
    def __init__(self, state_dir, keep=60, queue_size=4000):
        self.dir = os.path.join(state_dir, "logs", "trip_log")
        self.keep = int(keep)
        self.q = queue.Queue()
        self.limit = int(queue_size)
        self.active = False
        self.path = None
        self.dropped = 0
        self.error = ""                 # the writer's last disk problem; the node reports it
        self._thread = threading.Thread(target=self._run, name="trip_log", daemon=True)
        self._thread.start()

    # -- the control loop's side: never blocks, never raises ------------------------------
    def begin(self, label, now=None, **head):
        if self.active:
            self.end("superseded")
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        slug = "".join(c if c.isalnum() else "-" for c in str(label).lower())[:40].strip("-") or "run"
        self.path = os.path.join(self.dir, f"{stamp}-{slug}.jsonl.gz")
        self.active, self.dropped = True, 0
        self.q.put_nowait(("open", self.path))
        self.add("head", label=str(label), wall=time.time() if now is None else now, **head)

    def add(self, kind, **fields):
        if not self.active:
            return
        if kind in DROPPABLE and self.q.qsize() >= self.limit:
            self.dropped += 1
            return
        fields["k"] = kind
        self.q.put_nowait(fields)

    def end(self, result=""):
        if self.active:
            self.add("end", result=str(result), dropped=self.dropped)
            self.active = False
            self.q.put_nowait(("close", None))

    def drain_error(self):
        err, self.error = self.error, ""
        return err

    # -- the writer thread ------------------------------------------------------------------
    def close(self, timeout=5.0):
        """Finish what is queued and stop the writer (shutdown, tests)."""
        self.end("node stopped")
        self.q.put(_STOP)
        self._thread.join(timeout)

    def _run(self):
        fh, flushed = None, 0.0
        while True:
            try:
                item = self.q.get(timeout=FLUSH_S)
            except queue.Empty:
                item = None
            try:
                if item is _STOP:
                    fh = self._shut(fh)
                    return
                if isinstance(item, tuple):
                    fh = self._shut(fh)
                    if item[0] == "open":
                        os.makedirs(self.dir, exist_ok=True)
                        fh = gzip.open(item[1], "wt", compresslevel=1)
                    else:
                        fsutil.keep_newest(self.dir, self.keep, lambda f: f.endswith(".jsonl.gz"))
                elif item is not None and fh is not None:
                    fh.write(json.dumps(item, separators=(",", ":"), default=str) + "\n")
                if fh is not None and time.monotonic() - flushed >= FLUSH_S:
                    fh.flush()
                    flushed = time.monotonic()
            except (OSError, ValueError) as e:      # disk full, file gone: rows lost, loop alive
                self.error = str(e)
                fh = None

    @staticmethod
    def _shut(fh):
        if fh is not None:
            fh.close()
        return None


# -- reading ------------------------------------------------------------------------------
def read(path):
    """The rows of a log. A file cut short by a kill or power loss gives what it has."""
    rows = []
    try:
        with gzip.open(path, "rt") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    break
    except (EOFError, OSError):
        pass
    return rows


def latest(state_dir):
    d = os.path.join(state_dir, "logs", "trip_log")
    names = sorted(f for f in os.listdir(d) if f.endswith(".jsonl.gz")) if os.path.isdir(d) else []
    return os.path.join(d, names[-1]) if names else None


def _fmt(v, spec=".2f"):
    return "-" if v is None else format(v, spec)


def amcl_by_leg(rows):
    """{leg: {"n", "accepted", "min", "max"}}: how far AMCL lay from the taught path, per leg."""
    out = {}
    for r in rows:
        if r.get("k") != "amcl":
            continue
        b = out.setdefault(r.get("leg") or "?", {"n": 0, "accepted": 0, "min": None, "max": None})
        b["n"] += 1
        b["accepted"] += 1 if not r.get("verdict") else 0
        d = r.get("lateral")
        if d is not None:
            b["min"] = d if b["min"] is None else min(b["min"], d)
            b["max"] = d if b["max"] is None else max(b["max"], d)
    return out


def report(rows):
    """The run on a page: result, stops, forks, where AMCL disagreed, what went wrong."""
    head = next((r for r in rows if r.get("k") == "head"), {})
    end = next((r for r in reversed(rows) if r.get("k") == "end"), None)
    ticks = [r for r in rows if r.get("k") == "tick"]
    events = [r for r in rows if r.get("k") == "event"]
    lines = [f"run: {head.get('label', '?')}  graph {head.get('graph', '?')}  map {head.get('map', '?')}",
             f"result: {end['result'] if end else 'FILE ENDS WITHOUT A RESULT (node killed?)'}"
             + (f"; {end['dropped']} rows dropped" if end and end.get("dropped") else ""),
             f"rows: {len(ticks)} ticks, {sum(r.get('k') == 'amcl' for r in rows)} AMCL poses"]
    if ticks:
        lines.append(f"duration {ticks[-1]['t'] - ticks[0]['t']:.0f} s, "
                     f"followed {ticks[-1].get('travel', 0):.1f} m")
    lines += ["", "stops (S from the locator; check against the floor):"]
    lines += [f"  {r['text']}" for r in events if "at rest at" in r.get("text", "")] or ["  none"]
    lines += ["", f"{'fork':10}{'order':7}{'verdict':10}{'kept':>7}{'other':>7}{'single':>8}"
                  f"{'ticks':>6}{'S':>9}{'sigma':>7}"]
    forks = [r for r in rows if r.get("k") == "fork"]
    for f in forks:
        lines.append(f"{f.get('id', '?'):10}{f.get('order', '?'):7}{f.get('verdict', '?'):10}"
                     f"{_fmt(f.get('kept'), '.0f'):>7}{_fmt(f.get('other'), '.0f'):>7}"
                     f"{_fmt(f.get('single'), '.0f'):>8}{f.get('ticks', 0):>6}"
                     f"{_fmt(f.get('S')):>9}{_fmt(f.get('sigma'), '.3f'):>7}")
    if not forks:
        lines.append("  none")
    lines += ["", f"{'AMCL by leg':30}{'poses':>7}{'used':>7}{'lateral min..max m':>22}"]
    for leg, b in amcl_by_leg(rows).items():
        lines.append(f"{leg:30}{b['n']:>7}{b['accepted']:>7}{_fmt(b['min']):>12}..{_fmt(b['max'])}")
    zoned = [r for r in ticks if r.get("zone") and r.get("job") == "RUNNING"]
    if zoned:
        whys = {}
        for r in zoned:
            why = "HIGH" if r.get("high") else (r.get("high_why") or "envelope: a stop or fork is close")
            whys[why] = whys.get(why, 0) + 1
        lines += ["", f"inside high-speed zones ({len(zoned) * 0.02:.0f} s running):"]
        lines += [f"  {n * 0.02:6.1f} s  {why[:90]}" for why, n in sorted(whys.items(), key=lambda x: -x[1])]
    bad = [r for r in events if r.get("level") in ("warn", "error")]
    lines += ["", f"warnings and faults ({len(bad)}):"]
    lines += [f"  {r.get('text', '')[:150]}" for r in bad[:40]]
    return "\n".join(lines)


def fork_detail(rows, fork_id, before_s=2.0, after_s=3.0):
    """The ticks around one fork, for reading what the MLS and the wheels did."""
    fork = next((r for r in rows if r.get("k") == "fork" and r.get("id") == fork_id), None)
    if fork is None:
        return f"no fork {fork_id} in this log"
    t0 = fork.get("t", 0.0)
    out = [f"{'t':>7}{'nlcp':>5}  {'tracks mm':16}{'used':>6}{'intent':>9}{'L rpm':>7}{'R rpm':>7}"
           f"{'S':>9}"]
    for r in rows:
        if r.get("k") == "tick" and t0 - before_s <= r["t"] <= t0 + after_s:
            out.append(f"{r['t'] - t0:7.2f}{str(r.get('nlcp')):>5}  {str(r.get('tracks')):16}"
                       f"{str(r.get('e_used')):>6}{str(r.get('intent')):>9}"
                       f"{_fmt(r.get('left'), '.0f'):>7}{_fmt(r.get('right'), '.0f'):>7}"
                       f"{_fmt(r.get('S')):>9}")
    return "\n".join(out)
