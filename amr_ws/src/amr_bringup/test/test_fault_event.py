"""The supervisor's FAULT event carries the fault's code and reason (WP-T3, 2026-11-16).

test_fault_injection_sim expected a BASE_EXITED event on disk and found only
"MODE_CHANGE: IDLE -> FAULT: BASE_EXITED": the code was in the text, the reason (WP-H4's
"drive_node exited with code -6") nowhere in the event log. The follower and the executor
publish their state events under the state's own catalogue code; the supervisor now does too.
The real Supervisor._set runs against a plain object - no ROS graph.
"""

import threading
import types

from agv_core import alarms as cat

from amr_bringup import mode_fsm as fsm
from amr_bringup.supervisor_node import Supervisor


def fake(mode=fsm.IDLE):
    sv = types.SimpleNamespace()
    sv._lock = threading.RLock()
    sv.mode, sv.phase, sv.reason = mode, "", ""
    sv.fault_code, sv._last_fault = "", ""
    sv.events = []
    sv._event = lambda level, code, text: sv.events.append((level, code, text))
    sv.get_logger = lambda: types.SimpleNamespace(info=lambda *_: None)
    sv._mark = sv._publish_mode = sv._send_status = lambda: None
    sv._set = types.MethodType(Supervisor._set, sv)
    return sv


def test_a_fault_is_logged_under_its_own_code_with_its_reason():
    sv = fake()
    sv._set(fsm.FAULT, "fault", "drive_node exited with code -6 (SIGABRT); base exited unrequested",
            "BASE_EXITED")
    [(level, code, text)] = sv.events
    assert code == "BASE_EXITED" and code in cat.CATALOGUE
    assert "drive_node exited with code -6" in text and "-> FAULT" in text


def test_other_mode_changes_stay_mode_change():
    sv = fake()
    sv._set(fsm.LINE, "line", "ready")
    sv._set(fsm.LINE, "line", "ready")  # no change, no event
    assert [c for _, c, _ in sv.events] == ["MODE_CHANGE"]
