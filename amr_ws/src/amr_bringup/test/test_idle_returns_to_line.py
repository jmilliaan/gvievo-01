"""2026-10-29 (owner): on a tape vehicle IDLE is a way through, not a mode to park in.
A survey's end and a FAULT recovery commit IDLE and then start LINE by themselves; an
explicit IDLE request stays IDLE, and a trackless-only vehicle never enters LINE.

Failure mode: the LINE layer cannot start -> that transaction fails into FAULT as any
swap does, and the next Recover tries once more (one try per press, never a loop)."""

import types

import pytest
from bringup_fakes import Log

from amr_bringup import mode_fsm as fsm
from amr_bringup import operations as ops
from amr_bringup.supervisor_node import Supervisor


def fake(tracked):
    sv = types.SimpleNamespace()
    sv.book = ops.OperationBook(None)
    sv.tracked = tracked
    sv.mode, sv.generation, sv.requested = fsm.TRANSITIONING, 1, fsm.IDLE
    sv.txn, sv._pending_future, sv.inhibit_manual = None, None, True
    sv.active_map = ("", 0, "")
    sv.modes = []
    sv.get_logger = Log

    def _set(mode, phase="", reason="", fault=""):
        sv.mode = mode
        sv.modes.append(mode)

    sv._set = _set
    for name in ("_begin_transaction", "_enter_line", "_step_transaction"):
        setattr(sv, name, types.MethodType(getattr(Supervisor, name), sv))
    return sv


def commit_idle(sv, then_line, from_fault=False):
    op, _ = sv.book.submit("", fsm.REQ_RECOVER if from_fault else fsm.REQ_IDLE)
    sv._begin_transaction(op, fsm.IDLE, "", 0, "", from_fault=from_fault, then_line=then_line)
    sv.txn.step = fsm.COMMIT
    sv._step_transaction(0.0)
    return op


@pytest.mark.parametrize("tracked", [True, None])
@pytest.mark.parametrize("from_fault", [False, True])
def test_survey_end_and_recovery_go_back_to_line(tracked, from_fault):
    sv = fake(tracked)
    op = commit_idle(sv, then_line=True, from_fault=from_fault)
    assert sv.book.get(op.operation_id).status == ops.SUCCEEDED  # the survey/recover op ends at IDLE
    assert fsm.IDLE in sv.modes and sv.mode == fsm.TRANSITIONING
    assert sv.txn is not None and sv.txn.target == fsm.LINE and sv.txn.step == fsm.INHIBIT
    assert not sv.txn.then_line  # the LINE swap does not chain anything further
    assert sv.book.get(sv.txn.operation_id).kind == fsm.REQ_LINE


def test_an_explicit_idle_request_stays_idle():
    sv = fake(True)
    commit_idle(sv, then_line=False)
    assert sv.mode == fsm.IDLE and sv.txn is None


def test_a_trackless_vehicle_never_enters_line():
    sv = fake(False)
    commit_idle(sv, then_line=True)
    assert sv.mode == fsm.IDLE and sv.txn is None
