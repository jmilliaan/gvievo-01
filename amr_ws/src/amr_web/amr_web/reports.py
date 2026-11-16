"""Post-mortem in one press: a zip the operator can name over the phone.

"Verbose" belongs on disk, not on the screen. This packages everything an
engineer would otherwise SSH for - the event log, the last two hours of the
service journal and of the Wi-Fi watchdog's (journal-wifi.txt), the profile, the state
snapshot and the owners' diagnostics, with the drives' alarm history pulled out into drives.txt -
into `~/.amr/reports/report-YYYYmmdd-HHMMSS.zip`. The operator reads the file
name out; the engineer collects the file later.

The journal needs a sudoers line (RUNBOOK section 5). Without it the report is
still written, with a note in its place: a partial report beats no report.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import zipfile

from agv_core import fsutil

DIRNAME = "reports"
KEEP = 20
JOURNAL_SINCE = "-2h"
# The black box (unified plan WP-P6, amr_bringup.blackbox): the newest snapshot files under
# <state_dir>/blackbox. Each is up to the recorder's cache (16 MB): two keep the zip phone-sized.
BLACKBOX_DIR = "blackbox"
BLACKBOX_KEEP = 2


def _dir(state_dir: str) -> str:
    return os.path.join(os.path.expanduser(state_dir), DIRNAME)


RECORDED_EVENTS = "recorded_events.jsonl"  # amr_base.event_recorder.FILENAME (no ROS import here)


def _role_logs(state_dir: str) -> list[str]:
    """The live role logs AND the previous run's (`*.log.1`): after a crash or a power
    cut the interesting one is usually the run that ended, not the one that started
    (power-loss plan W2)."""
    log_dir = os.path.join(os.path.expanduser(state_dir), "logs")
    try:
        names = sorted(os.listdir(log_dir))
    except OSError:
        return []
    return [
        os.path.join(log_dir, n)
        for n in names
        if ((n.endswith(".log") or n.endswith(".log.1")) and not n.startswith("events"))
        # the base's own event record (event_recorder, WP-H3) and its rotations: the evidence that
        # survives the web being down (unified plan WP-H2, 2026-11-16)
        or n.startswith(RECORDED_EVENTS)
    ]


def _journal() -> str:
    return _journal_of("amr.service")


def _wifi_journal() -> str:
    """agv-wifi-reconnect logs to the journal only (unified plan WP-H3): its last two hours, so a
    STATION_LINK_DOWN in the events has the repair attempts beside it."""
    return _journal_of("agv-wifi-reconnect.service")


def _journal_of(unit: str) -> str:
    cmd = ["sudo", "-n", "journalctl", "-u", unit, "--since", JOURNAL_SINCE, "--no-pager"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as e:
        return f"(journal unavailable: {e})\n"
    if p.returncode != 0:
        return (
            "(journal unavailable: the sudoers line for journalctl is not installed; "
            f"see RUNBOOK section 5)\n\n{(p.stderr or '').strip()}\n"
        )
    return p.stdout


_NAME_LOCK = threading.Lock()
_CLAIMED: set[str] = set()  # names being written right now


def _profile_path() -> str:
    """The profile this process loaded; the vehicle default when none was."""
    try:
        from agv_core import config  # noqa: PLC0415 - the web may run without a profile

        loaded = getattr(config, "PROFILE_PATH_LOADED", None)
        if loaded:
            return loaded
    except Exception:  # noqa: BLE001
        pass
    return os.path.join(os.path.expanduser("~/agv_can"), "profiles", "agv-01.json")


def blackbox_files(state_dir: str, keep: int = BLACKBOX_KEEP) -> list[str]:
    """The newest `keep` .mcap snapshots, newest first. Each was written at a FAULT/stop edge;
    `ros2 bag reindex <dir> -s mcap` restores its metadata (written only at recorder exit)."""
    root = os.path.join(os.path.expanduser(state_dir), BLACKBOX_DIR)
    found = []
    for d, _dirs, names in os.walk(root):
        for n in names:
            if n.endswith(".mcap"):
                p = os.path.join(d, n)
                try:
                    found.append((os.stat(p).st_mtime, p))
                except OSError:
                    continue
    return [p for _t, p in sorted(found, reverse=True)[:keep]]


def drive_history(diagnostics: dict) -> str:
    """The drives' fault and alarm history, from drive_node's /diagnostics (unified plan WP-B4):
    603Fh (the drive's last alarm, NON-volatile: it survives the power cycle that cleared it)
    and 1003h (the volatile error list) as the last preflight read them, the latched EMCY and
    the link's fault. The first file to read after "it stopped"; diagnostics.json has the rest."""
    bus = (diagnostics.get("can/bus") or {}).get("values") or {}
    lines = []
    if bus:
        fault = " ".join(x for x in (bus.get("fault_code", ""), bus.get("fault_reason", "")) if x)
        lines.append(f"link {bus.get('link_state', '?')}; fault: {fault or 'none'}")
    for name in sorted(k for k in diagnostics if k.startswith("drive/")):
        d = diagnostics[name] or {}
        v = d.get("values") or {}
        lines.append(
            f"{name[len('drive/'):]} ({d.get('hardware_id', '')}): state {v.get('state', '?')}; "
            f"alarm {v.get('alarm') or 'none'}; "
            f"last alarm 603Fh {v.get('alarm_history_603F') or 'not read'}; "
            f"error history 1003h {v.get('error_history_1003') or 'not read'}"
            + (f"; boot-up frame {v['boot_up_age_s']} s ago" if v.get("boot_up_age_s") else "")
        )
    return "\n".join(lines) + "\n" if lines else "(no drive diagnostics received)\n"


def build(
    state_dir: str,
    state: dict,
    events: list[dict],
    diagnostics: dict,
    event_files: list[str],
    note: str = "",
) -> str:
    """Write one report; returns its file name. Raises OSError only if the reports
    directory itself cannot be written - a missing input is recorded, not fatal."""
    out_dir = _dir(state_dir)
    os.makedirs(out_dir, exist_ok=True)
    # Unique even for two requests in the same second, and written to a staging name that
    # listing() ignores, then renamed: a listed report is always complete (audit R18).
    with _NAME_LOCK:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"report-{stamp}.zip"
        n = 1
        while os.path.exists(os.path.join(out_dir, name)) or name in _CLAIMED:
            n += 1
            name = f"report-{stamp}-{n}.zip"
        _CLAIMED.add(name)
    path = os.path.join(out_dir, name)
    staging = os.path.join(out_dir, f".{name}.{os.getpid()}.{threading.get_ident()}.part")
    with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("note.txt", note or "(no note)")
        z.writestr("state.json", json.dumps(state, indent=2, default=str))
        z.writestr("events.json", json.dumps(events, indent=2, default=str))
        z.writestr("diagnostics.json", json.dumps(diagnostics, indent=2, default=str))
        z.writestr("drives.txt", drive_history(diagnostics))
        z.writestr("journal.txt", _journal())
        z.writestr("journal-wifi.txt", _wifi_journal())
        for src in list(event_files) + _role_logs(state_dir):
            try:
                z.write(src, os.path.join("logs", os.path.basename(src)))
            except OSError as e:
                z.writestr(f"logs/{os.path.basename(src)}.missing", str(e))
        bb_root = os.path.join(os.path.expanduser(state_dir), BLACKBOX_DIR)
        for src in blackbox_files(state_dir):
            try:
                z.write(src, os.path.join(BLACKBOX_DIR, os.path.relpath(src, bb_root)))
            except OSError as e:
                z.writestr(f"{BLACKBOX_DIR}/{os.path.basename(src)}.missing", str(e))
        for src in (os.path.join(os.path.expanduser(state_dir), "operations.jsonl"), _profile_path()):
            if os.path.exists(src):
                try:
                    z.write(src, os.path.basename(src))
                except OSError:
                    pass
    os.replace(staging, path)
    with _NAME_LOCK:
        _CLAIMED.discard(name)
    _prune(out_dir)
    return name


def _prune(out_dir: str) -> None:
    try:
        fsutil.keep_newest(out_dir, KEEP, lambda n: n.startswith("report-") and n.endswith(".zip"))
    except OSError:
        pass


def listing(state_dir: str) -> list[dict]:
    out_dir = _dir(state_dir)
    rows = []
    try:
        names = os.listdir(out_dir)
    except OSError:
        return rows
    for name in sorted(names, reverse=True):
        if not (name.startswith("report-") and name.endswith(".zip")):
            continue
        full = os.path.join(out_dir, name)
        try:
            stat = os.stat(full)
        except OSError:
            continue
        rows.append({"name": name, "bytes": stat.st_size, "t": stat.st_mtime})
    return rows


def path_of(state_dir: str, name: str) -> str | None:
    """Resolve a report name to a path, refusing anything that is not a plain name in
    the reports directory (a name comes from a URL)."""
    if not name or "/" in name or "\\" in name or not name.startswith("report-") or not name.endswith(".zip"):
        return None
    path = os.path.join(_dir(state_dir), name)
    return path if os.path.exists(path) else None
