"""The HTTP server for the operator pages (unified plan WP-E5, S-`waitress-wsgi`, 2026-11-16).

waitress when it is installed: a fixed pool of worker threads, HTTP/1.1 keep-alive (the
jog's 10 Hz refresh no longer pays a TCP handshake per POST over Wi-Fi: werkzeug's
development server always answers `Connection: close`), and all socket I/O on the main
thread, so a roaming tablet that stalls mid-request holds a buffer, not a worker.
No fork: the rclpy executors keep running on their own threads.

Without waitress (a unit not yet updated) the werkzeug server still starts, with a warning
and a socket timeout on every connection (H-P2-9: no thread pile-up from a tablet that
walked out of range).

Jog under a fixed pool: one jog refresh is in flight per browser at a time (jogpad.js sends
the next only after the reply), and server.py's jog_lock serialises the session either way.
"""

from __future__ import annotations

import importlib

# Worker threads. Three browsers at once (kiosk, tablet, engineer laptop), each with up to
# four requests in flight (jog refresh, 5 Hz live pose, state, alarms) = 12; plus 4 for
# service calls, which hold a worker up to adapter.CALL_TIMEOUT_S (6 s). An idle worker is
# a blocked thread: no CPU.
THREADS = 16
# Idle keep-alive connections are closed after this (waitress channel_timeout); the same
# value is the werkzeug fallback's per-socket timeout.
CHANNEL_TIMEOUT_S = 30


def _werkzeug_handler():
    from werkzeug.serving import WSGIRequestHandler  # noqa: PLC0415

    class TimeoutHandler(WSGIRequestHandler):
        timeout = CHANNEL_TIMEOUT_S  # socketserver: settimeout() on the connection

    return TimeoutHandler


def serve(app, host: str, port: int, warn=print, _import=importlib.import_module) -> str:
    """Serve `app` until the process ends. Returns which server ran ("waitress" / "werkzeug")."""
    try:
        waitress = _import("waitress")
    except ImportError as e:
        warn(f"waitress is not installed ({e}); serving with the werkzeug development server. "
             "Install it as alpha-setup says (pip, pinned)")
        app.run(host=host, port=port, threaded=True, use_reloader=False, request_handler=_werkzeug_handler())
        return "werkzeug"
    waitress.serve(app, host=host, port=port, threads=THREADS, channel_timeout=CHANNEL_TIMEOUT_S, ident=None)
    return "waitress"
