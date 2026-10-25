"""eventlog.EventRing: the one event history behind RosAdapter and the demo (lean plan D59)."""

import pathlib
import sys

from amr_web.eventlog import EventLog, EventRing


class SpyLog:
    def __init__(self, tail=()):
        self.appended, self._tail = [], list(tail)

    def tail(self, n):
        return self._tail[-n:]

    def append(self, e, sync=False):
        self.appended.append((e["code"], sync))

    def files(self):
        return ["events.jsonl"]


def ev(code, level="info"):
    return {"t": 0.0, "source": "x", "level": level, "code": code, "text": "", "seq": 0}


def test_numbers_are_monotonic_and_the_oldest_falls_off():
    r = EventRing(maxlen=3)
    for k in range(5):
        r.add(ev(f"C{k}"))
    assert [e["n"] for e in r.since()] == [3, 4, 5]
    assert [e["code"] for e in r.since(4)] == ["C4"]


def test_restore_marks_the_tail_and_numbering_continues():
    log = SpyLog(tail=[ev("OLD1"), ev("OLD2")])
    r = EventRing(maxlen=300, log=log)
    assert r.restore() == 2
    r.add(ev("NEW"))
    rows = r.since()
    assert [(e["code"], e["n"], e.get("restored", False)) for e in rows] == [
        ("OLD1", 1, True), ("OLD2", 2, True), ("NEW", 3, False)]


def test_every_event_reaches_the_log_and_only_errors_are_synced():
    log = SpyLog()
    r = EventRing(log=log)
    r.add(ev("A"))
    r.add(ev("B", "error"))
    assert log.appended == [("A", False), ("B", True)]
    assert "n" not in r.log.appended[0]  # the disk line carries no ring number
    assert r.files() == ["events.jsonl"]


def test_without_a_log_nothing_is_written_or_restored():
    r = EventRing(log=None)
    assert r.restore() == 0 and r.files() == []
    assert r.add(ev("A"))["n"] == 1


def test_a_real_log_round_trips_through_a_restart(tmp_path):
    path = str(tmp_path / "logs" / "events.jsonl")
    EventRing(log=EventLog(path)).add(ev("BEFORE"))
    after = EventRing(log=EventLog(path))
    after.restore()
    assert [(e["code"], e["restored"]) for e in after.since()] == [("BEFORE", True)]


def test_the_demo_records_a_page_error(tmp_path):
    """The demo adapter had no emit(): /api/page-error raised on the offline demo."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
    import demo_server  # noqa: PLC0415

    app, demo = demo_server.build(str(tmp_path / "maps"), str(tmp_path / "state"))
    c = app.test_client()
    assert c.post("/api/page-error", json={"where": "home", "what": "boom"}).status_code == 200
    rows = c.get("/api/events").get_json()
    assert rows[-1]["code"] == "WEB_BUG" and rows[-1]["text"] == "home: boom"
    assert demo.event_log_files() == []
