"""The wire enums' names, in one place: ModeState, RunState, LineState, MuxState,
LocalizationState, MappingState, OperationState, CommissioningState and the
RequestSurvey operations.

Pure: no rclpy, no amr_interfaces import, so the web server, the demo, the bag
report and the tests use the same tables the nodes do. The values are the msg
constants (test_wire_contract.py pins every table against them). mode_fsm keeps
the mode ints it switches on; gating keeps the mux ints. APPEND ONLY, like the msgs.
"""

from amr_base import gating

MODE_NAMES = {
    0: "STARTING",
    1: "IDLE",
    2: "MAPPING",
    3: "NAVIGATION",
    4: "TRANSITIONING",
    5: "FAULT",
    6: "STOPPING",
    7: "LINE",
}
MODE_IDLE, MODE_NAVIGATION, MODE_LINE = 1, 3, 7

RUN_NAMES = {0: "IDLE", 1: "READY", 2: "EXECUTING", 3: "PAUSED", 4: "BLOCKED", 5: "FAULT", 6: "DONE"}

LINE_NAMES = {0: "IDLE", 1: "ARMED", 2: "RUNNING", 3: "HOLD", 4: "DONE", 5: "FAULT"}
# ARMED, RUNNING, HOLD: a line run is under way (the layer may not be swapped out).
LINE_HELD = (1, 2, 3)

MUX_NAMES = gating.NAMES

LOC_NAMES = {0: "UNLOCALIZED", 1: "CHECKING", 2: "READY", 3: "LOST"}
LOC_READY, LOC_LOST = 2, 3

MAPPING_NAMES = {0: "IDLE", 1: "MAPPING", 2: "RETURN_REVIEW", 3: "SAVING", 4: "SAVED"}

OP_NAMES = {0: "PENDING", 1: "SUCCEEDED", 2: "FAILED", 3: "INTERRUPTED"}

COMMISSIONING_NAMES = {0: "IDLE", 1: "PREPARED", 2: "RUNNING", 3: "SETTLING", 4: "DONE", 5: "ABORTED"}
COMMISSIONING_BUSY = (1, 2, 3)  # PREPARED, RUNNING, SETTLING

SURVEY_OPS = {"start": 0, "returned": 1, "save": 2, "abort": 3}  # RequestSurvey.operation
