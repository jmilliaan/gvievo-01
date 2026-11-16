#!/usr/bin/env python3
"""Write the "call the engineer" page for the kiosk (unified plan WP-H5).

Run as root by amr-failed.service, which amr.service names in OnFailure=. Installed
by install.sh as /usr/local/sbin/amr-failed (root runs a root-owned copy, never the
operator-writable repo file, like agv-wifi-reconnect).

The page goes to /run/amr/failed.html (directory 0755, file 0644): the kiosk runs
as amrkiosk, which cannot read the service user's home, and /run is tmpfs, so a
stale page never survives a boot. amr.service's ExecStartPre removes it. The kiosk
(deploy/kiosk/amr-kiosk-browser, FALLBACK=) shows it only while amr.service is
failed and the page exists, and goes back to the UI when the service recovers.

The page says what the operator does (call the engineer) and what the engineer
looks at first. One failure is named on its own: the identity mismatch.
amr-supervisor.sh exits before the supervisor when agv_core.identity refuses the
profile, the restart limit then leaves the unit failed, and only the engineer at
the PC can fix it (vehicle.env), never a button. Standard library only.
"""

from __future__ import annotations

import html
import os
import socket
import subprocess
import sys
import time

OUT = "/run/amr/failed.html"
UNIT = "amr.service"
TAIL = 15

# systemd's Result= of the failed unit, in words.
RESULT_TEXT = {
    "start-limit-hit": "it failed to start several times in a row and systemd stopped retrying",
    "exit-code": "the vehicle software exited with an error",
    "signal": "the vehicle software was killed by a signal",
    "core-dump": "the vehicle software crashed",
    "watchdog": "the vehicle software stopped answering the watchdog",
    "timeout": "the vehicle software did not start or stop in time",
    "oom-kill": "the PC ran out of memory",
    "protocol": "the vehicle software broke the systemd start protocol",
    "resources": "systemd could not set the service up",
}
IDENTITY_MARK = "must run profile"  # agv_core.identity.check()'s refusal sentence


def _run(argv: list[str], timeout: float = 5.0) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def unit_state(show=_run) -> dict[str, str]:
    out = show(["systemctl", "show", UNIT, "-p", "Result", "-p", "ExecMainStatus", "-p", "NRestarts",
                "-p", "InvocationID", "-p", "ActiveState"])
    state = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        state[k] = v
    # systemd >= 251 also hands an OnFailure= unit the failed unit's result directly
    if os.environ.get("MONITOR_SERVICE_RESULT"):
        state["Result"] = os.environ["MONITOR_SERVICE_RESULT"]
    return state


def journal_tail(invocation: str, journal=_run) -> list[str]:
    """The failed unit's last lines: this invocation when systemd says which, else the boot."""
    if invocation:
        lines = journal(["journalctl", f"_SYSTEMD_INVOCATION_ID={invocation}", "-n", "200",
                         "--no-pager", "-o", "cat"])
        if lines.strip():
            return lines.splitlines()
    return journal(["journalctl", "-u", UNIT, "-b", "-n", "200", "--no-pager", "-o", "cat"]).splitlines()


def render(state: dict[str, str], lines: list[str], host: str, now: float) -> str:
    """The page. Pure: every input is passed in; journal text is escaped."""
    result = state.get("Result", "")
    identity = [ln for ln in lines if "identity:" in ln and IDENTITY_MARK in ln]
    esc = html.escape
    if identity:
        why = ("This PC is set up as the wrong vehicle, so the vehicle software refused to start. "
               "Nothing was started.")
        steps = [
            esc(identity[-1].strip()),
            "Check the one line <code>AGV_PROFILE=agv-NN</code> in <code>~/.amr/vehicle.env</code> "
            "(alpha-setup.md section 5.3) against the host name, or fix the host name.",
            "Then: <code>sudo systemctl reset-failed amr &amp;&amp; sudo systemctl start amr</code>",
        ]
    else:
        why = "The vehicle software stopped and did not restart"
        why += f": {RESULT_TEXT[result]}." if result in RESULT_TEXT else "."
        steps = [
            "Read why: <code>journalctl -u amr.service -b</code> (the last lines are below).",
            "Fix the cause, then: "
            "<code>sudo systemctl reset-failed amr &amp;&amp; sudo systemctl start amr</code>",
            "If the drives do not arm afterwards, switch them off and on.",
        ]
    facts = (f"{esc(host)} &middot; {esc(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)))} &middot; "
             f"result {esc(result or '?')} &middot; "
             f"exit status {esc(state.get('ExecMainStatus', '?'))} &middot; "
             f"restarts {esc(state.get('NRestarts', '?'))}")
    tail = "\n".join(esc(ln) for ln in lines[-TAIL:]) or "(no journal lines)"
    items = "".join(f"<li>{s}</li>" for s in steps)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Call the engineer</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{margin:0;padding:24px;background:#7a1010;color:#fff;font:20px/1.4 sans-serif}}
h1{{font-size:40px;margin:0 0 12px}} p.why{{font-size:24px}} code{{background:#0003;padding:0 4px}}
ol{{background:#0002;padding:12px 12px 12px 40px}} pre{{background:#000;color:#ddd;font-size:13px;
padding:8px;white-space:pre-wrap;word-break:break-all;max-height:40vh;overflow:auto}}
.facts{{font-size:15px;opacity:.85}}
</style></head><body>
<h1>Call the engineer</h1>
<p class="why">{esc(why)}</p>
<p>The vehicle will not move. Leave it as it is; the screen goes back to normal by itself
when the software runs again.</p>
<h2>For the engineer</h2>
<ol>{items}</ol>
<p class="facts">{facts}</p>
<pre>{tail}</pre>
</body></html>
"""


def write(page: str, out: str = OUT) -> None:
    """Directory 0755, file 0644 (the kiosk user reads it), replaced atomically."""
    d = os.path.dirname(out)
    os.makedirs(d, exist_ok=True)
    os.chmod(d, 0o755)
    tmp = f"{out}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(page)
    os.chmod(tmp, 0o644)
    os.replace(tmp, out)


def main() -> int:
    state = unit_state()
    lines = journal_tail(state.get("InvocationID", ""))
    write(render(state, lines, socket.gethostname(), time.time()))
    print(f"amr-failed: wrote {OUT} (result {state.get('Result', '?')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
