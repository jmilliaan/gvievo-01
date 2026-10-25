"""agv_core.fsutil: rotation, atomic JSON, tolerant JSONL, pruning (lean plan D29)."""
import json
import os
import stat
import tempfile

from helpers import check

from agv_core import fsutil


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test_fsutil():
    print("\nfsutil: numbered rotation, atomic json, jsonl, keep newest")
    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, "base.log")
        for gen in ("a", "b", "c", "d"):
            _write(log, gen)
            fsutil.rotate_numbered(log, keep=3)
        got = [open(f"{log}.{n}").read() for n in (1, 2, 3)]
        check("rotation shifts .1 -> .2 -> .3 and the oldest falls off",
              got == ["d", "c", "b"] and not os.path.exists(f"{log}.4") and not os.path.exists(log), str(got))
        fsutil.rotate_numbered(log, keep=3)
        check("rotating an absent file does nothing", open(f"{log}.1").read() == "d")

        pin = os.path.join(d, "sub", "web.json")
        fsutil.atomic_write_json(pin, {"engineer_pin": "x"}, mode=0o600, indent=2)
        check("atomic json creates the directory, writes the document and its mode",
              json.load(open(pin)) == {"engineer_pin": "x"}
              and stat.S_IMODE(os.stat(pin).st_mode) == 0o600
              and not os.path.exists(pin + ".tmp"))
        try:
            fsutil.atomic_write_json(pin, {"bad": object()})
        except TypeError:
            pass
        check("a failed write keeps the old file and leaves no temp file",
              json.load(open(pin)) == {"engineer_pin": "x"} and not os.path.exists(pin + ".tmp"))
        ptr = os.path.join(d, "line_graph.json")
        fsutil.atomic_write_json(ptr, [1], indent=1, mkstemp=True)
        check("mkstemp mode leaves no .tmp- file behind",
              json.load(open(ptr)) == [1] and not [n for n in os.listdir(d) if n.startswith(".tmp-")])

        jl = os.path.join(d, "events.jsonl")
        _write(jl, '{"a": 1}\n\nnot json\n[2]\n{"a": 3')
        check("jsonl yields every value in order, skipping blank, bad and half-written lines",
              list(fsutil.iter_jsonl(jl)) == [{"a": 1}, [2]])

        for n in range(5):
            _write(os.path.join(d, f"report-{n}.zip"), "")
        removed = fsutil.keep_newest(d, 2, lambda n: n.startswith("report-"))
        left = sorted(n for n in os.listdir(d) if n.startswith("report-"))
        check("keep_newest removes all but the last N by name and touches nothing else",
              left == ["report-3.zip", "report-4.zip"] and len(removed) == 3 and os.path.exists(jl),
              str(left))
        check("keep 0 removes nothing (the old [:-0] slice)", fsutil.keep_newest(d, 0, lambda n: True) == [])


TESTS = [test_fsutil]
