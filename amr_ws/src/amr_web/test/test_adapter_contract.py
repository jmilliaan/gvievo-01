"""server.Adapter is what create_app calls; RosAdapter (adapter.py) is what the vehicle runs.
The Protocol drifted (nine members called but not declared). Pinned from the source, so no ROS
graph is needed (lean plan D05). The demo side is test_demo_contract.py."""

import ast
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "amr_web"


def _tree(name):
    return ast.parse((PKG / name).read_text())


def _class(tree, name):
    return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)


def _called_on_adapter():
    return {n.attr for n in ast.walk(_tree("server.py"))
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "adapter"}


def _protocol():
    cls = _class(_tree("server.py"), "Adapter")
    out = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    return out | {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)}


def _ros_members():
    cls = _class(_tree("adapter.py"), "RosAdapter")
    out = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    for n in ast.walk(cls):  # attributes set in methods (self.live = ...)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" \
                and isinstance(n.ctx, ast.Store):
            out.add(n.attr)
    return out


def test_the_protocol_declares_every_member_the_server_uses():
    called = _called_on_adapter()
    assert len(called) > 25  # the walk found the server's calls at all
    assert called <= _protocol(), sorted(called - _protocol())


def test_the_ros_adapter_implements_the_protocol():
    missing = _protocol() - _ros_members()
    assert not missing, sorted(missing)


# ---- WP-C12 / WP-E5 (2026-11-16): the service clients and their timeouts -----------------


def _module_consts(tree):
    """Top-level NAME = <number> / NAME = OTHER_NAME assignments of a module."""
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            v = n.value
            if isinstance(v, ast.Constant) and isinstance(v.value, (int, float)):
                out[n.targets[0].id] = float(v.value)
            elif isinstance(v, ast.Name) and v.id in out:
                out[n.targets[0].id] = out[v.id]
    return out


def test_the_service_clients_live_on_the_second_node():
    """C#20: 23 clients in the subscription executor's wait set, rebuilt on every wake-up."""
    tree = _tree("adapter.py")
    cls = _class(tree, "RosAdapter")
    on_self = [n.lineno for n in ast.walk(cls) if isinstance(n, ast.Attribute) and n.attr == "create_client"
               and isinstance(n.value, ast.Name) and n.value.id == "self"]
    assert not on_self, f"self.create_client at lines {on_self}: use the calls node"
    assert "self.calls.create_client" in ast.unparse(cls)
    spinner = ast.unparse(_class(tree, "Spinner"))
    assert "add_node(adapter.calls)" in spinner and "calls_thread" in spinner, "nothing spins the calls node"


def test_every_service_wait_ends_before_the_browser_gives_up():
    """WP-E5: the browser aborts a request after REQUEST_TIMEOUT_MS; a server worker waiting
    longer answers nobody. line_mission, line_teach and the Trigger calls name their own."""
    import re  # noqa: PLC0415

    tree = _tree("adapter.py")
    c = _module_consts(tree)
    js = (PKG / "static" / "amr.js").read_text(encoding="utf-8")
    browser_s = int(re.search(r"REQUEST_TIMEOUT_MS = (\d+)", js).group(1)) / 1000.0
    assert c["CALL_TIMEOUT_S"] <= browser_s - 2.0, "leave the server's answer time to arrive"
    cls = _class(tree, "RosAdapter")
    seen = 0
    for n in ast.walk(cls):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in (
                "_call", "_call_why", "_trigger"):
            for kw in n.keywords:
                if kw.arg == "timeout":
                    v = kw.value
                    val = v.value if isinstance(v, ast.Constant) else c.get(getattr(v, "id", ""))
                    assert val is not None and 0 < val <= c["CALL_TIMEOUT_S"], ast.unparse(n)
                    seen += 1
    assert seen >= 12
    meths = {f.name: ast.unparse(f) for f in cls.body if isinstance(f, ast.FunctionDef)}
    assert "timeout=LINE_MISSION_TIMEOUT_S" in meths["line_mission"]
    assert "timeout=LINE_TEACH_TIMEOUT_S" in meths["line_teach"]
    assert "timeout=RECOVER_TIMEOUT_S" in meths["recover"]
    assert "timeout: float=QUICK_TIMEOUT_S" in meths["_trigger"]
    assert "min(float(timeout), CALL_TIMEOUT_S)" in meths["_call_why"], "the ceiling holds for any caller"


class _Fut:
    def __init__(self, result):
        self._r = result

    def done(self):
        return self._r is not None

    def result(self):
        return self._r


class _Client:
    srv_name = "/amr/x"

    def __init__(self, ready, result=None):
        self.ready, self._result, self.waits = ready, result, []

    def wait_for_service(self, timeout_sec):
        self.waits.append(timeout_sec)
        return self.ready

    def call_async(self, req):
        return _Fut(self._result)


def test_a_call_is_bounded_and_says_why(monkeypatch):
    import time  # noqa: PLC0415

    import pytest  # noqa: PLC0415

    pytest.importorskip("rclpy")  # the vehicle: adapter.py imports rclpy
    from amr_web import adapter as ad  # noqa: PLC0415

    a = ad.RosAdapter.__new__(ad.RosAdapter)
    a._srv = {"gone": _Client(False), "slow": _Client(True), "ok": _Client(True, "answer")}
    assert a._call_why("gone", object(), 3.0) == (None, "unavailable")
    assert a._srv["gone"].waits == [2.0], "the discovery wait stays bounded"
    t0 = time.monotonic()
    assert a._call_why("slow", object(), 0.2) == (None, "timeout")
    assert time.monotonic() - t0 < 1.0
    assert a._call_why("ok", object(), 0.2) == ("answer", "")
    ok, msg = a._trigger("slow", timeout=0.2)
    assert not ok and "no answer within 0.2 s" in msg
    monkeypatch.setattr(ad, "CALL_TIMEOUT_S", 0.2)
    t0 = time.monotonic()
    assert a._call_why("slow", object(), 60.0) == (None, "timeout")
    assert time.monotonic() - t0 < 1.0, "a caller's long timeout is capped"
