"""*** TRIAL ONLY (2026-10-07) - DELETE WITH tape_run.TRIAL_ALWAYS_BRANCH_RIGHT. ***

Every run takes the RIGHT track at diverters, plain line following included,
and says so once in the operator events.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
for _p in (ROOT, os.path.join(ROOT, "amr_ws", "src", "amr_line"), os.path.dirname(__file__)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_mission_engine import World  # noqa: E402

from amr_line import branch, tape_run  # noqa: E402

TWO_TRACKS = {"tracks": [{"index": 1, "pos_mm": -40, "width": 10}, {"index": 2, "pos_mm": 30, "width": 10}],
              "has_track": True, "nlcp": 3, "track_level": 5}


def test_the_trial_flag_is_on_and_every_run_defaults_right():
    assert tape_run.TRIAL_ALWAYS_BRANCH_RIGHT is True, "trial over? delete this file with the flag"
    w = World(None)
    w.start()
    assert w.job.tape.branch.ladder.intent() == branch.RIGHT
    events = [text for _, text in w.job.tape.drain_events()]
    assert sum("TRIAL policy: always branch RIGHT" in e for e in events) == 1


def test_at_a_diverter_the_right_track_is_chosen():
    w = World(None)
    w.start()
    track, choice = w.job.tape.branch.choose(3, TWO_TRACKS["tracks"], 0.0)
    assert choice == branch.RIGHT and track is not None
