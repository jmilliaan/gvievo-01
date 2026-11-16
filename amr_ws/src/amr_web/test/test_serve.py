"""WP-E5 (2026-11-16): waitress when installed, the werkzeug server with a warning when not."""

import types

from amr_web import serve


class _App:
    def __init__(self):
        self.run_kwargs = None

    def run(self, **kw):
        self.run_kwargs = kw


def test_waitress_serves_with_a_bounded_pool_and_no_server_header():
    seen = {}
    fake = types.SimpleNamespace(serve=lambda app, **kw: seen.update(kw, app=app))
    app, warnings = _App(), []
    assert serve.serve(app, "0.0.0.0", 5001, warnings.append, _import=lambda name: fake) == "waitress"
    assert seen == {"app": app, "host": "0.0.0.0", "port": 5001, "threads": serve.THREADS,
                    "channel_timeout": serve.CHANNEL_TIMEOUT_S, "ident": None}
    assert app.run_kwargs is None and warnings == []


def test_without_waitress_the_werkzeug_server_still_starts_with_a_socket_timeout():
    def missing(name):
        raise ImportError(f"No module named '{name}'")

    app, warnings = _App(), []
    assert serve.serve(app, "0.0.0.0", 5001, warnings.append, _import=missing) == "werkzeug"
    assert len(warnings) == 1 and "waitress" in warnings[0]
    kw = app.run_kwargs
    assert kw["threaded"] is True and kw["use_reloader"] is False
    assert (kw["host"], kw["port"]) == ("0.0.0.0", 5001)
    # H-P2-9: a tablet that roams out mid-request releases its thread after the timeout
    assert kw["request_handler"].timeout == serve.CHANNEL_TIMEOUT_S


def test_the_pool_covers_jog_and_polling_from_three_browsers_plus_slow_calls():
    """Each browser: one jog refresh in flight (jogpad.js waits for the reply), the 5 Hz live
    pose, state and alarms = 4. Three browsers = 12, plus room for service calls that hold a
    worker up to the adapter's 6 s ceiling."""
    assert serve.THREADS >= 3 * 4 + 4
    assert serve.CHANNEL_TIMEOUT_S >= 10, "keep-alive must outlast the 1 s polls between requests"
