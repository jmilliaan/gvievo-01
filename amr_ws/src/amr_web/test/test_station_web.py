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
