"""What a run leaves behind: the event ring, the CSV, the PNG."""
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

def test_event_log():
    """A stop reason has to outlive a page reload, and the buffer must not be
    floodable from a per-tick path."""
    print("\noperator event log")
    import events

    events.clear()
    check("empty buffer reports seq 0", events.latest_seq() == 0)
    s1 = events.info("armed in manual mode")
    s2 = events.warn("line lost")
    check("sequence numbers advance", s2 > s1, f"{s1} -> {s2}")

    latest, items = events.since(0)
    check("since(0) returns everything", len(items) == 2 and latest == s2)
    _, newer = events.since(s1)
    check("since(seq) returns only newer", [e["seq"] for e in newer] == [s2])
    check("entries carry level and message",
          newer[0]["level"] == "warn" and newer[0]["msg"] == "line lost")

    for i in range(events.MAX_EVENTS + 50):
        events.info(f"filler {i}")
    _, items = events.since(0)
    check("ring buffer is bounded", len(items) == events.MAX_EVENTS,
          f"{len(items)} retained, cap {events.MAX_EVENTS}")
    check("oldest entries are the ones dropped",
          all("filler" in e["msg"] for e in items))

    def hammer():
        for _ in range(300):
            events.info("x")
    ts = [threading.Thread(target=hammer) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    _, items = events.since(0)
    seqs = [e["seq"] for e in items]
    check("concurrent emit keeps sequence numbers unique and ordered",
          len(set(seqs)) == len(seqs) and seqs == sorted(seqs))
    check("an unknown level does not raise",
          events.emit("bogus", "still recorded") > 0)
    events.clear()

    # The 50 Hz paths must never emit - one chatty call site empties the whole
    # buffer of anything meaningful in about four seconds.
    src = (ROOT / "canworker.py").read_text()

    def method_body(name, text=src):
        """Source of one method, ending at the NEXT def rather than a named one.

        Slicing to a named successor silently widens the window when someone
        inserts a method between the two, which turns this check into a false
        positive against a method it was never meant to cover.
        """
        start = text.index(f"def {name}")
        nxt = text.find("\n    def ", start + 1)
        return text[start:nxt if nxt != -1 else len(text)]

    check("_run_autopilot() never emits",
          "events." not in method_body("_run_autopilot"))
    win = src[src.index("class _LoopHealth"):src.index("class Controller")]
    check("_LoopHealth never emits", "events." not in win)
    check("driver faults are edge-tracked, not polled",
          "_fault_seen" in src)


def test_run_plot():
    """The plot is generated on STOP inside the service; a crash there must not
    be able to reach the control thread, and the PNG must be a real PNG."""
    import struct
    import plotrun
    import runlog
    print("\nrun plot rendering")

    rows = [dict(t=i * 0.02, state="run" if i < 400 else "stopping",
                 e_mm=12.0 * math.sin(i * 0.05), n_l=800.0, n_r=790.0,
                 rpm_l=798.0, rpm_r=788.0) for i in range(450)]
    png = plotrun.render(rows, title="test", subtitle="gains")
    check("emits a PNG signature", png[:8] == b"\x89PNG\r\n\x1a\n")
    w, h = struct.unpack(">II", png[16:24])
    check("IHDR is the requested pixel size", (w, h) == (1700, 850), f"{w}x{h}")
    check("width/height are honoured", struct.unpack(
        ">II", plotrun.render(rows, width=900, height=500)[16:24]) == (900, 500))

    check("empty input does not raise", plotrun.render([])[:4] == b"\x89PNG")

    # Fixed axes are what make two runs comparable by eye. An out-of-range point
    # must clip at the frame rather than quietly rescaling and defeating that.
    lims = {}
    real_render = plotrun.render

    def capture(rws, **kw):
        plt = plotrun._pyplot()
        out = real_render(rws, **kw)
        lims["fig_count"] = len(plt.get_fignums())
        return out

    spiky = [dict(r) for r in rows]
    spiky[10]["e_mm"] = 900.0
    a = capture(rows, err_range=(-30.0, 30.0), rpm_range=(0.0, 2500.0))
    b = capture(spiky, err_range=(-30.0, 30.0), rpm_range=(0.0, 2500.0))
    check("an out-of-range point does not change the frame size",
          struct.unpack(">II", a[16:24]) == struct.unpack(">II", b[16:24]))
    check("the outlier still changes the image (drawn, then clipped)", a != b)
    check("figures are closed, not leaked", lims["fig_count"] == 0,
          f"{lims['fig_count']} open figures")

    stats = plotrun._stats(rows)
    check("stats line reports duration and RMS",
          "Duration" in stats and "RMS" in stats and "Avg L" in stats, stats)
    check("stats ignores non-run rows",
          plotrun._stats([dict(t=0.0, state="stopping", e_mm=500.0,
                               n_l=0.0, n_r=0.0, rpm_l=0.0, rpm_r=0.0)])
          is not None)
    check("all-None error column does not raise",
          plotrun.render([dict(t=i * 0.02, state="run", e_mm=None, n_l=1.0,
                               n_r=1.0, rpm_l=1.0, rpm_r=1.0)
                          for i in range(10)])[:4] == b"\x89PNG")

    # Decimation must keep the extremes: a one-tick spike is exactly the thing
    # worth seeing, and dropping it would make the plot lie about the run.
    spiky = [dict(t=i * 0.02, state="run", e_mm=0.0, n_l=800.0, n_r=800.0,
                  rpm_l=800.0, rpm_r=800.0) for i in range(20000)]
    spiky[7777]["e_mm"] = 99.0
    spiky[9999]["e_mm"] = -77.0
    kept = plotrun._decimate(spiky, 1000, 0.0, spiky[-1]["t"])
    check("decimation thins a long run", len(kept) < len(spiky) / 4,
          f"{len(spiky)} -> {len(kept)} rows")
    es = [r["e_mm"] for r in kept]
    check("decimation preserves the error envelope",
          max(es) == 99.0 and min(es) == -77.0,
          f"kept max {max(es)} min {min(es)}")
    check("decimated rows stay in time order",
          all(kept[i]["t"] <= kept[i + 1]["t"] for i in range(len(kept) - 1)))

    # A bad row must set .error, not propagate out of close().
    lg = runlog.RunLog()
    lg.path = "/nonexistent/dir/run.csv"
    lg.plot_path = "/nonexistent/dir/run.png"
    lg.dir = "/nonexistent/dir"
    lg._render()
    check("a plot failure is captured, never raised",
          lg.error is not None and lg.plot_path is None, str(lg.error)[:50])

    # matplotlib must not be dragged into the control process at import time -
    # it costs seconds and ~100 MB, and only the render thread ever needs it.
    src = (ROOT / "core" / "plotrun.py").read_text()
    head = src[:src.index("def _pyplot")]
    check("plotrun does not import matplotlib at module level",
          "import matplotlib" not in head and "import pyplot" not in head)
    check("the Agg backend is selected before pyplot",
          src.index('matplotlib.use("Agg")') < src.index("import matplotlib.pyplot"))


def test_run_numbering():
    """Run directories are NNNN-auto_<stamp>, numbered from what is on disk.

    The sequence is the thing a human cites ("run 17"), so it has to be
    monotonic, gap-tolerant, and immune to two runs landing in the same second -
    which the bare timestamp scheme was not.
    """
    import shutil
    import tempfile
    import runlog
    print("\nrun log numbering")

    saved = runlog.LOG_DIR
    tmp = tempfile.mkdtemp()
    try:
        runlog.LOG_DIR = tmp
        check("an empty log directory starts at 1", runlog.next_seq(tmp) == 1)
        check("a missing log directory starts at 1",
              runlog.next_seq(os.path.join(tmp, "nope")) == 1)

        for n in (1, 7, 17):
            os.makedirs(os.path.join(tmp, f"{n:04d}-auto_20260901_120000"))
        check("numbering continues from the highest prefix present",
              runlog.next_seq(tmp) == 18, "0001/0007/0017 -> 18")

        os.makedirs(os.path.join(tmp, "auto_20260901_130000"))
        os.makedirs(os.path.join(tmp, "notes"))
        check("unprefixed entries are ignored", runlog.next_seq(tmp) == 18)

        os.makedirs(os.path.join(tmp, "10000-auto_20260901_120000"))
        check("the prefix survives passing 9999", runlog.next_seq(tmp) == 10001)

        shutil.rmtree(tmp)
        os.makedirs(tmp)
        dirs = []
        for _ in range(3):
            lg = runlog.RunLog()
            lg.open("numbering")
            lg.write({"state": "run", "e_mm": 1.0, "dt": 0.02}, {"loop_ms": 20.0})
            lg.close(plot=False)
            dirs.append(os.path.basename(lg.dir))
        check("consecutive runs number 1, 2, 3",
              [d[:4] for d in dirs] == ["0001", "0002", "0003"], " ".join(dirs))
        # The old bare-timestamp name collided here and the second run silently
        # overwrote the first one's CSV.
        check("runs in the same second get distinct directories",
              len(set(dirs)) == 3)

        shutil.rmtree(os.path.join(tmp, dirs[1]))
        lg = runlog.RunLog()
        lg.open()
        lg.close(plot=False)
        check("a deleted run leaves a gap, never a collision",
              os.path.basename(lg.dir).startswith("0004"),
              os.path.basename(lg.dir))

        # LOG_DIR must be read at call time; as a default argument it would
        # freeze at import and this redirect would be silently ignored.
        check("next_seq() honours a reassigned LOG_DIR",
              runlog.next_seq() == 5, str(runlog.next_seq()))
    finally:
        runlog.LOG_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)


TESTS = [
    test_event_log,
    test_run_plot,
    test_run_numbering,
]
