"""amr.service must stop before the CAN bridge, or a PC reboot latches both drives in FAULT."""

from pathlib import Path

UNIT = Path(__file__).resolve().parents[3] / "deploy" / "amr.service"


def test_amr_service_stops_before_the_can_bridge():
    after = [ln for ln in UNIT.read_text().splitlines() if ln.startswith("After=")]
    assert any("canable@can0.service" in ln for ln in after), after
