#!/usr/bin/env python3
"""A line run's log on a page (amr_line.trip_log). Offline, no ROS.

    tools/trip_report.py                     the latest run
    tools/trip_report.py <file.jsonl.gz>     that run
    tools/trip_report.py --fork J-SPLIT      tick by tick around one fork
"""
import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "amr_ws" / "src" / "amr_line")]

from amr_line import trip_log  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="a trip log; default the latest")
    ap.add_argument("--fork", help="show the ticks around this fork")
    ap.add_argument("--state-dir", default=os.environ.get("AMR_STATE_DIR", os.path.expanduser("~/.amr")))
    a = ap.parse_args()
    path = a.file or trip_log.latest(a.state_dir)
    if not path:
        sys.exit(f"no trip logs under {a.state_dir}/logs/trip_log")
    rows = trip_log.read(path)
    print(path)
    print(trip_log.fork_detail(rows, a.fork) if a.fork else trip_log.report(rows))


if __name__ == "__main__":
    main()
