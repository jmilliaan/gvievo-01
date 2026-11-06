"""amr_line.trip_log: the whole run on disk, written off the control thread, never in its way."""
import gzip
import os
import pathlib
import queue
import subprocess
import sys
import types

import pytest
import test_site_run

from amr_line import job as lj  # noqa: E402
from amr_line import trip_log as tl  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[4]


def a_run(path_dir, keep=60):
    log = tl.TripLog(str(path_dir), keep=keep)
    log.begin("MRU: MRU4", now=1000.0, graph="g2", map="m")
    log.add("route", stops=[{"id": "ATT", "S": 1.0}])
    for k in range(5):
        log.add("tick", t=float(k), travel=k * 0.4, S=k * 0.4, nlcp=2, tracks=[1], left=1.0, right=1.0)
    log.add("amcl", t=1.0, x=0.1, y=0.2, verdict="", leg="L1", lateral=0.02)
    log.add("amcl", t=2.0, x=0.1, y=0.2, verdict="+0.12 m from the taught path", leg="L1", lateral=0.12)
    log.add("event", t=1.5, code="X", level="warn", text="line RUNNING: at rest at ATT, +4 cm from it")
    log.add("fork", t=2.0, id="J-SPLIT", order="left", verdict="other", kept=90, other=-30, single=-32,
            ticks=9, S=212.6, sigma=0.03)
    log.end("DONE at HOME-N")
    return log


def test_a_run_is_written_and_reported(tmp_path):
    log = a_run(tmp_path)
    log.close()
    rows = tl.read(log.path)
    assert [r["k"] for r in rows][:2] == ["head", "route"]
    assert rows[-1] == {"result": "DONE at HOME-N", "dropped": 0, "k": "end"}
    text = tl.report(rows)
    assert "MRU: MRU4" in text and "DONE at HOME-N" in text and "at rest at ATT" in text
    assert "J-SPLIT" in text and "other" in text and "0.02..0.12" in text.replace(" ", "")
    assert tl.amcl_by_leg(rows)["L1"] == {"n": 2, "accepted": 1, "min": 0.02, "max": 0.12}
    assert "nlcp" in tl.fork_detail(rows, "J-SPLIT") and "no fork" in tl.fork_detail(rows, "J-X")


def test_nothing_is_written_between_runs(tmp_path):
    log = tl.TripLog(str(tmp_path))
    log.add("tick", t=1.0)
    log.end("nothing")
    log.close()
    assert log.path is None and not os.path.isdir(log.dir)


def test_behind_the_high_rate_rows_are_dropped_and_counted_and_the_rest_always_go_in(tmp_path):
    log = tl.TripLog(str(tmp_path), queue_size=4)
    log.q = queue.Queue()                           # the writer is parked on the old queue
    log.active = True
    for k in range(50):
        log.add("tick", t=k)
    assert log.dropped == 46 and log.q.qsize() == 4
    log.add("event", t=1.0, text="a fault")
    log.add("fork", t=1.0, id="J")
    log.end("FAULT")
    kept = [log.q.get_nowait() for _ in range(log.q.qsize())]
    assert [r["k"] for r in kept[4:7]] == ["event", "fork", "end"] and kept[-1] == ("close", None)
    assert kept[6]["dropped"] == 46


def test_a_disk_problem_is_reported_and_the_log_goes_on(tmp_path):
    (tmp_path / "logs").write_text("a file where the directory should be")
    log = tl.TripLog(str(tmp_path))
    log.begin("run", now=0.0)
    log.add("tick", t=1.0)
    log.end("x")
    log.close()
    assert log.error, "reported"
    assert log.drain_error() and not log.drain_error()


def test_a_log_cut_short_still_reads(tmp_path):
    path = tmp_path / "cut.jsonl.gz"
    with gzip.open(path, "wt") as fh:
        fh.write('{"k":"head","label":"run"}\n{"k":"tick","t":0.0,"travel":0.0}\n')
    raw = path.read_bytes()
    path.write_bytes(raw[:-6])
    rows = tl.read(str(path))
    assert rows and rows[0]["k"] == "head"
    assert "FILE ENDS WITHOUT A RESULT" in tl.report(rows)


def test_old_logs_are_pruned_and_latest_finds_the_newest(tmp_path):
    log = tl.TripLog(str(tmp_path), keep=2)
    for k in range(4):
        log.begin(f"run {k}", now=1000.0 + 100 * k)
        log.end("x")
    log.close()
    names = sorted(os.listdir(log.dir))
    assert len(names) == 2 and tl.latest(str(tmp_path)).endswith(names[-1])


def test_the_report_tool_runs(tmp_path):
    a_run(tmp_path).close()
    tool = str(ROOT / "tools" / "trip_report.py")
    out = subprocess.run([sys.executable, tool, "--state-dir", str(tmp_path)],
                         capture_output=True, text=True, check=True).stdout
    assert "J-SPLIT" in out


def node_over(world, log):
    """The node's own logging methods, on a real job through a real trip."""
    from amr_line.line_follow_node import LineFollowNode as N

    from amr_line import tape_locator
    snap = {"leg": "L", "health": "HEALTHY", "amcl_out": "", "lateral": 0.01, "rejected": 0,
            "last_reject": ""}
    loc = types.SimpleNamespace(snapshot=lambda: dict(snap, S=world.S, sigma=world.sigma))
    rt = types.SimpleNamespace(loc=loc, p=tape_locator.Params(), graph_name="t g1", sel={"map_id": "t"})
    n = types.SimpleNamespace(
        job=world.job, triplog=log, tapeloc=rt, reader=types.SimpleNamespace(sensor=world.tape),
        _generation=1,
        _wheels=types.SimpleNamespace(left_vel_rad_s=0.5, right_vel_rad_s=0.5), _tl_route=None, _tl_forks=0,
        _tl_tick=0, _tl_ready=None, _tl_failed=False, get_logger=lambda: types.SimpleNamespace(
            error=lambda m: pytest.fail(m), warn=lambda m: pytest.fail(m)))
    n.running = 0
    n._tl_inputs = None
    n._trip_log_begin = lambda: N._trip_log_begin(n)
    n._trip_log_safe = lambda fn, *a: N._trip_log_safe(n, fn, *a)
    n._trip_log_row = lambda *a: N._trip_log_row(n, *a)
    real = world.job.tick

    def tick(i):
        before = world.job.state
        n._tl_inputs = i
        out = real(i)
        n.running += world.job.state == lj.RUNNING
        if world.job.trip_new is not None:
            n._tl_route = world.job.trip_new
        N._trip_log_tick(n, i.now, before, out[0], out[1])
        return out

    world.job.tick = tick
    return n


def test_the_node_logs_a_whole_trip_every_fork_and_the_end(tmp_path):
    w = test_site_run.tape_end_world()
    log = tl.TripLog(str(tmp_path), queue_size=10 ** 6)     # this world runs faster than real time
    n = node_over(w, log)
    test_site_run.drive_tape_end_trip(w, 0.02)
    assert not log.active, "the end of the run closes the log"
    path = log.path
    log.close()
    rows = tl.read(path)
    kinds = {r["k"] for r in rows}
    assert {"head", "route", "tick", "fork", "end"} <= kinds, kinds
    assert [r["id"] for r in rows if r["k"] == "fork"] == ["J-B", "J-C"]
    assert all(r["verdict"] == "ordered" for r in rows if r["k"] == "fork")
    assert rows[-1]["k"] == "end" and rows[-1]["result"].startswith("DONE") and rows[-1]["dropped"] == 0
    ticks = [r for r in rows if r["k"] == "tick"]
    assert len(ticks) > 1000 and {"RUNNING", "HOLD"} <= {r["job"] for r in ticks}
    assert any(r["nlcp"] in (3, 6) and r["armed"] for r in ticks), "the fork's ticks are there"
    assert sum(r["job"] == "RUNNING" for r in ticks) == n.running, "RUNNING has every tick"
    assert {r["auto"] for r in ticks} == {True} and {r["link"] for r in ticks} and "field_clear" in ticks[0]
    assert all(r["field_clear"] is not None for r in ticks)
    assert "J-C" in tl.report(rows) and "armed" not in tl.fork_detail(rows, "J-C").split("\n")[0]


def test_a_bug_in_the_logging_is_reported_once_and_the_tick_goes_on():
    from amr_line.line_follow_node import LineFollowNode as N
    said = []

    def boom(*_a):
        raise KeyError("x")

    n = types.SimpleNamespace(_trip_log_row=boom, _tl_failed=False,
                              _trip_log_safe=lambda fn, *a: N._trip_log_safe(n, fn, *a),
                              triplog=types.SimpleNamespace(drain_error=lambda: ""),
                              get_logger=lambda: types.SimpleNamespace(error=said.append))
    N._trip_log_tick(n, 0.0, 0, 0.0, 0.0)
    N._trip_log_tick(n, 0.0, 0, 0.0, 0.0)
    assert len(said) == 1 and "goes on" in said[0]
