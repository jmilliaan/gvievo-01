"""Per-run log of the auto control loop. One directory per START/STOP cycle.

Each run produces logs/auto_YYYYmmdd_HHMMSS/ holding run.csv and run.png, so a
run is a single self-contained thing to copy, attach or delete.

Gains are file constants and a change costs a service restart, so each run has to
yield usable data first time - this is what makes tuning evidence-based rather
than guesswork.

Rows are buffered and flushed about once a second. The control loop runs on the
bus thread, which also has to service 100 Hz sensor frames and blocking SDO
transfers; a per-row write would put filesystem latency straight into that path.
Nothing here may raise: a logging problem must never stop the vehicle.
"""
import os
import re
import threading
import time

import plotrun

# Anchored to the REPO ROOT, not to this file. runlog.py lives in core/, so
# dirname(__file__) would be core/ and every run would quietly land in
# core/logs/ - no error, just numbering restarting at 0001 beside the real runs.
# If this module ever moves again, this line moves with it.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(_ROOT, "logs")
FLUSH_PERIOD_S = 1.0
CSV_NAME = "run.csv"
PNG_NAME = "run.png"

# Run directories are NNNN-auto_YYYYmmdd_HHMMSS. The sequence number is what
# a human cites ("run 17"); the timestamp is what makes it findable.
SEQ_RE = re.compile(r"^(\d{4,})-")
STAMP_FMT = "auto_%Y%m%d_%H%M%S"


def next_seq(directory=None):
    """Highest NNNN- prefix already in the log directory, plus one.

    Derived from what is on disk rather than held in a counter file: there is
    no separate state to fall out of step with the directory, and an archived
    or deleted run leaves a gap rather than making the next run collide with a
    name that still exists.

    Never raises. A missing log directory is the first-run case and yields 1.

    LOG_DIR is read at CALL time, not bound as a default argument - a default
    would freeze the module constant at import and silently ignore any later
    reassignment, which is exactly what a test that redirects the log directory
    does.
    """
    directory = LOG_DIR if directory is None else directory
    highest = 0
    try:
        for name in os.listdir(directory):
            m = SEQ_RE.match(name)
            if m:
                highest = max(highest, int(m.group(1)))
    except OSError:                             # no logs/ yet, or unreadable
        pass
    return highest + 1

COLUMNS = [
    "t", "dt", "state",
    "e_mm", "e_used", "p", "i", "d", "omega_cmd",
    "speed_red", "v_base", "n_l", "n_r", "sat_scale",
    "rpm_l", "rpm_r", "has_track", "n_tracks", "guard",
    "sw_l", "sw_r", "loop_ms", "branch", "slow", "k_used",
]


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


class RunLog:
    """Open on START, close on STOP. Disabled instances are silently inert."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.dir = None
        self.seq = None           # run number, assigned at open()
        self.path = None          # the CSV; the UI links this
        self.plot_path = None
        self.note = ""
        self._fh = None
        self._buf = []
        self._t0 = None
        self._last_flush = 0.0
        self.error = None

    def open(self, note=""):
        if not self.enabled:
            return
        try:
            self.seq = next_seq()
            self.dir = os.path.join(
                LOG_DIR, f"{self.seq:04d}-" + time.strftime(STAMP_FMT))
            os.makedirs(self.dir, exist_ok=True)
            self.path = os.path.join(self.dir, CSV_NAME)
            self.plot_path = os.path.join(self.dir, PNG_NAME)
            self.note = note
            self._fh = open(self.path, "w", buffering=1)
            if note:
                self._fh.write(f"# {note}\n")
            self._fh.write(",".join(COLUMNS) + "\n")
            self._t0 = time.monotonic()
            self._last_flush = self._t0
        except Exception as e:                  # noqa: BLE001 - never fatal
            self.error = str(e)
            self._fh = None

    def write(self, diag, extra=None):
        if self._fh is None:
            return
        try:
            row = dict(diag)
            if extra:
                row.update(extra)
            row["t"] = time.monotonic() - self._t0
            self._buf.append(",".join(_fmt(row.get(c)) for c in COLUMNS))
            now = time.monotonic()
            if now - self._last_flush >= FLUSH_PERIOD_S:
                self._drain()
                self._last_flush = now
        except Exception as e:                  # noqa: BLE001
            self.error = str(e)

    def _drain(self):
        if self._fh is None or not self._buf:
            return
        self._fh.write("\n".join(self._buf) + "\n")
        self._buf = []

    def close(self, plot=True):
        """Flush and close, then render the plot off-thread.

        Rendering walks every row and compresses a 1180x640 bitmap - about a
        second of pure Python. STOP must not wait for that, so it runs on a
        daemon thread that re-reads the finished CSV. Re-reading rather than
        keeping rows in memory costs nothing in the control path and makes the
        plot a picture of what was actually written.
        """
        if self._fh is None:
            return
        try:
            self._drain()
            self._fh.close()
        except Exception as e:                  # noqa: BLE001
            self.error = str(e)
        finally:
            self._fh = None
        if plot and self.path:
            threading.Thread(target=self._render, name="runplot",
                             daemon=True).start()

    def _render(self):
        try:
            import config          # local: plotrun stays vehicle-agnostic
            rows, note = read_csv(self.path)
            png = plotrun.render(
                rows,
                title=os.path.basename(self.dir or "auto run"),
                subtitle=note,
                # Fixed axes from the profile, so two runs are comparable by eye.
                # Traces clip at the frame rather than rescaling the plot.
                rpm_range=(0.0, config.PLOT_RPM_MAX),
                err_range=(-config.PLOT_ERR_RANGE_MM, config.PLOT_ERR_RANGE_MM))
            with open(self.plot_path, "wb") as fh:
                fh.write(png)
        except Exception as e:                  # noqa: BLE001 - never fatal
            self.error = f"plot: {e}"
            self.plot_path = None


def _f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def read_csv(path):
    """(rows, header_note). Only the columns the plot needs are converted."""
    import csv
    note = ""
    with open(path) as fh:
        lines = []
        for line in fh:
            if line.startswith("#"):
                note = note or line[1:].strip()
            else:
                lines.append(line)
    rows = []
    for d in csv.DictReader(lines):
        rows.append({
            "t": _f(d.get("t")) or 0.0,
            "state": d.get("state") or "",
            "e_mm": _f(d.get("e_mm")),
            "n_l": _f(d.get("n_l")),
            "n_r": _f(d.get("n_r")),
            "rpm_l": _f(d.get("rpm_l")),
            "rpm_r": _f(d.get("rpm_r")),
        })
    return rows, note
