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
