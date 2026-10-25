"""line_follow_node's four engineer Triggers share one handler (lean plan D105)."""

import pathlib
import types

from amr_line.line_follow_node import LineFollowNode

SRC = (pathlib.Path(__file__).resolve().parents[1] / "amr_line" / "line_follow_node.py").read_text()


def test_the_handler_replies_logs_under_its_label_and_publishes():
    logs = []
    n = types.SimpleNamespace(get_logger=lambda: types.SimpleNamespace(info=logs.append),
                              _publish_state=lambda: logs.append("published"))
    res = types.SimpleNamespace(success=None, message=None)
    assert LineFollowNode._trigger(n, "speed toggle high", lambda: (False, "not running"), res) is res
    assert (res.success, res.message) == (False, "not running")
    assert logs == ["speed toggle high: not running", "published"]


def test_the_log_labels_are_the_old_ones():
    for label in ('f"branch order {side}"', 'f"speed toggle {level}"', 'f"forced U-turn {act}"',
                  'f"continue {act}"'):
        assert label in SRC, label
