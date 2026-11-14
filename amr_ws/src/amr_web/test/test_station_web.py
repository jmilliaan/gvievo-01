"""Station call plan P3: no web route reaches an order, and the Run page follows the switch."""

import pathlib
import re

import pytest
from test_operator_ux import app_for

PKG = pathlib.Path(__file__).resolve().parents[1]


def test_no_web_route_reaches_the_order_service():
    """Searches for the service name. The indirect path, a web action removing a block, is pinned by
    test_settling_blocks_for_its_time_after_each_restart and
    test_clear_in_fault_is_refused_with_calling_on."""
    for path in (
        list((PKG / "amr_web").rglob("*.py"))
        + list((PKG / "amr_web").rglob("*.html"))
        + list((PKG / "amr_web").rglob("*.js"))
    ):
        text = path.read_text(errors="replace")
        assert '/amr/line/order"' not in text and "/amr/line/order'" not in text, path.name
    server = (PKG / "amr_web" / "server.py").read_text()
    m = re.search(r"TRIP_ACTIONS = \(([^)]*)\)", server)
    assert m.group(1) == '"call", "cancel", "confirm_released", "confirm_off", "status"'


@pytest.mark.parametrize("on", [False, True])
def test_run_page_text_follows_the_switch(tmp_path, monkeypatch, on):
    from agv_core import config

    monkeypatch.setattr(config, "STATION_ENABLED", on)
    client, _stub = app_for({}, tmp_path)
    assert client.get("/api/line/site").get_json()["calling"] is on
    page = client.get("/run").data
    assert b'id="lt-warn"' in page and b"Motion starts only" in page, "the markup stays either way"
    assert b"Station calling is ON" in page and b"if (site.calling)" in page, "the swap is on site.calling"


def test_run_calls_with_calling_on_only_cancel_a_waiting_call(tmp_path):
    """One queue (owner 2026-11-13): with calling on, a machine button not waiting is greyed; the job's
    trip_call refuses a new call anyway (amr_line test_on_run_calls_takes_no_new_call_of_any_group)."""
    client, _stub = app_for({}, tmp_path)
    page = client.get("/run").data
    assert b"if (!waiting.has(b.dataset.machine)) b.disabled = true;" in page
    assert b"calls come from the station buttons" in page


def test_the_order_tile_returns_after_the_last_wait_in_use(tmp_path):
    """A BTU lap leaves me_status "": 'returning' keys on the last wait in use, me for MRU."""
    client, _stub = app_for({}, tmp_path)
    page = client.get("/run").data
    assert b"const last = o.me_status || used[used.length - 1];" in page
    assert b"last === 'FINISHED' ? 'returning'" in page
