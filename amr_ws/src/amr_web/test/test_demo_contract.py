"""The offline demo (tools/demo_server.py) serves the real create_app over a DemoAdapter. It drifts
silently: a method server.py calls that the demo lacks, or binds differently, is a 500 only
someone clicking the demo ever sees (lean plan D06)."""

import ast
import inspect
import pathlib
import sys

import pytest

SERVER = pathlib.Path(__file__).resolve().parents[1] / "amr_web" / "server.py"
TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"


def _calls():
    """(method, positional count, keyword names) for every adapter.<method>(...) in server.py."""
    def is_adapter_attr(f):
        return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "adapter"

    out = set()
    for n in ast.walk(ast.parse(SERVER.read_text())):
        if not isinstance(n, ast.Call):
            continue
        if is_adapter_attr(n.func):
            out.add((n.func.attr, len(n.args), tuple(sorted(k.arg for k in n.keywords if k.arg))))
        elif isinstance(n.func, ast.Name) and n.func.id == "_call" and n.args and is_adapter_attr(n.args[0]):
            out.add((n.args[0].attr, len(n.args) - 1, ()))  # _call(adapter.x, *args)
    return sorted(out)


def _guarded(name):
    return f'hasattr(adapter, "{name}")' in SERVER.read_text()


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    sys.path.insert(0, str(TOOLS))
    import demo_server  # noqa: PLC0415

    tmp = tmp_path_factory.mktemp("demo")
    return demo_server.build(str(tmp / "maps"), str(tmp / "state"))[1]


def test_every_server_call_binds_on_the_demo_or_is_guarded(demo):
    problems = []
    for name, npos, kws in _calls():
        fn = getattr(demo, name, None)
        if fn is None:
            if not _guarded(name):
                problems.append(f"{name}: missing on the demo and not hasattr-guarded in server.py")
            continue
        try:
            inspect.signature(fn).bind(*([None] * npos), **{k: None for k in kws})
        except TypeError as e:
            problems.append(f"{name}({npos} args, {kws}): {e}")
    assert not problems, "\n".join(problems)


def _ros_state_keys():
    """The keys of the dict RosAdapter.state() returns, read from adapter.py."""
    tree = ast.parse((SERVER.parent / "adapter.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RosAdapter")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "state")
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
    return {k.value for k in ret.value.keys if isinstance(k, ast.Constant)}


def test_the_demo_state_uses_only_real_keys(demo):
    real = _ros_state_keys()
    assert len(real) > 20  # the parse found the real dict
    extra = set(demo.state()) - real
    assert not extra, f"demo state keys RosAdapter does not have: {sorted(extra)}"


def test_the_demo_admits_mode_requests_by_the_supervisor_rules(demo):
    """D06: refusals come from mode_fsm.admit, operations from OperationBook."""
    from amr_bringup import mode_fsm as fsm  # noqa: PLC0415

    demo.scenario("executing")
    ok, op_id, why = demo.request_mode(fsm.IDLE, "", 0, "")
    # admit checks the wheels before the run: which refusal comes first depends on the sim tick
    assert not ok and op_id == "", why
    assert why in ("vehicle not proven stopped (fresh, still wheels for 0.5 s)",
                   "a mission is READY/EXECUTING/PAUSED/BLOCKED; abort it first"), why
    demo.scenario("idle")
    import time  # noqa: PLC0415

    time.sleep(0.15)  # the sim loop stops the wheels within one 0.05 s tick
    ok, op_id, why = demo.request_mode(fsm.NAVIGATION, "sim_factory", 1, "")
    assert ok, why
    op = demo.get_operation(op_id)
    assert op["status_name"] == "SUCCEEDED" and op["kind"] == "mode" and op["phase"] == "done"
    assert demo.state()["mode"]["mode"] == fsm.NAVIGATION
    assert demo.get_operation("nope") is None


def test_the_demo_reads_the_profile_for_wheels_and_io(demo):
    import demo_server  # noqa: PLC0415
    from agv_core import config  # noqa: PLC0415

    assert demo_server.DI_NAMES == list(config.DIO_DI_NAMES)
    assert demo_server.DI_AUTO == config.PANEL_DI_AUTO
    demo.panel["mode_auto"] = True
    assert demo.io_image()["di"][config.PANEL_DI_AUTO] is True
    assert demo_server.GEAR_RATIO == config.GEAR_RATIO
