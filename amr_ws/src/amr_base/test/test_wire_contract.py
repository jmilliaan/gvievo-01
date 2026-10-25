"""amr_base.wire against the msgs it names, and every module that keeps an enum table
against wire (lean plan D04). A wrong value mislabels the HMI and the bag report, or
silences the alarm horn; this fails first."""

import pytest

from amr_base import gating, panel_io, wire

msgs = pytest.importorskip("amr_interfaces.msg")
srvs = pytest.importorskip("amr_interfaces.srv")


def _constants(cls):
    return {v: k for k, v in vars(cls).items()
            if k.isupper() and isinstance(v, int) and not k.startswith("_")}


@pytest.mark.parametrize(
    "table, msg",
    [
        (wire.MODE_NAMES, "ModeState"),
        (wire.RUN_NAMES, "RunState"),
        (wire.LINE_NAMES, "LineState"),
        (wire.LOC_NAMES, "LocalizationState"),
        (wire.MAPPING_NAMES, "MappingState"),
        (wire.OP_NAMES, "OperationState"),
        (wire.COMMISSIONING_NAMES, "CommissioningState"),
    ],
)
def test_each_table_is_exactly_the_msg_constants(table, msg):
    assert table == _constants(getattr(msgs, msg))


def test_mux_names_are_the_msg_constants_lowercased():
    assert {v: k.lower() for v, k in _constants(msgs.MuxState).items()} == wire.MUX_NAMES == gating.NAMES


def test_survey_operations_match_request_survey():
    want = {k.lower(): v for v, k in _constants(srvs.RequestSurvey.Request).items()}
    assert wire.SURVEY_OPS == want


def test_named_subsets_are_the_states_they_say():
    L, C, M, Lo = msgs.LineState, msgs.CommissioningState, msgs.ModeState, msgs.LocalizationState
    assert wire.LINE_HELD == (L.ARMED, L.RUNNING, L.HOLD)
    assert wire.COMMISSIONING_BUSY == (C.PREPARED, C.RUNNING, C.SETTLING)
    assert (wire.MODE_IDLE, wire.MODE_NAVIGATION, wire.MODE_LINE) == (M.IDLE, M.NAVIGATION, M.LINE)
    assert (wire.LOC_READY, wire.LOC_LOST) == (Lo.READY, Lo.LOST)


def test_the_alarm_horn_sets_name_the_states_they_mean():
    L, R = msgs.LineState, msgs.RunState
    assert panel_io.LINE_ACTIVE == (L.RUNNING, L.HOLD)
    assert panel_io.RUN_ACTIVE == (R.EXECUTING, R.BLOCKED)
    assert panel_io.LINE_PREMOVE == L.ARMED


def test_the_authorities_use_wire():
    from amr_bringup import mode_fsm, operations
    from amr_line import job
    from amr_localization import readiness
    from amr_mission import run_fsm

    assert mode_fsm.MODE_NAMES == wire.MODE_NAMES
    assert run_fsm.NAMES is wire.RUN_NAMES and job.STATE_NAMES is wire.LINE_NAMES
    assert readiness.NAMES is wire.LOC_NAMES
    ops = {operations.PENDING, operations.SUCCEEDED, operations.FAILED, operations.INTERRUPTED}
    assert ops == set(wire.OP_NAMES)
