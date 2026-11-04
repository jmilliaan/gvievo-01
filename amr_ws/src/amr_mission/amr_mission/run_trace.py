"""A small always-on trace of each run, so speed and pose exist without a bag (2026-11-04).

One CSV per run in ~/.amr/logs/run-traces, one row per RunState publish (2 Hz). Evidence only:
every operation is best-effort and failures are swallowed, because a full disk must not stop
the vehicle. A run_log.sh bag stays the tool for anything finer than 2 Hz.
"""

from __future__ import annotations

import os
import time

KEEP = 100
HEADER = (
    "t,run_id,state,step_id,step_type,step_v_mps,left_rad_s,right_rad_s,"
    "x_m,y_m,yaw_rad,cross_track_m,localization_state,hold_cause"
)


class RunTrace:
    def __init__(self, directory: str, keep: int = KEEP) -> None:
        self.directory = directory
        self.keep = keep
        self._run_id = ""
        self._fh = None

    def write(self, run_id: str, *fields) -> None:
        """Append one row (time is added here). A new run_id starts a new file."""
        try:
            if run_id != self._run_id or self._fh is None:
                self.close()
                self._open(run_id)
            row = ",".join(f"{f:.4f}" if isinstance(f, float) else str(f) for f in fields)
            self._fh.write(f"{time.time():.2f},{run_id},{row}\n")
            self._fh.flush()  # a power cut loses a row at most
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        try:
            if self._fh is not None:
                self._fh.close()
        except OSError:
            pass
        self._fh = None
        self._run_id = ""

    def _open(self, run_id: str) -> None:
        os.makedirs(self.directory, exist_ok=True)
        path = os.path.join(self.directory, f"{run_id}.csv")
        new = not os.path.exists(path)
        self._fh = open(path, "a")  # noqa: SIM115 - held open for the run
        self._run_id = run_id
        if new:
            self._fh.write(HEADER + "\n")
            self._prune()

    def _prune(self) -> None:
        names = sorted(n for n in os.listdir(self.directory) if n.endswith(".csv"))
        for name in names[: max(0, len(names) - self.keep)]:
            os.remove(os.path.join(self.directory, name))
