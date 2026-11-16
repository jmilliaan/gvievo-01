"""Every `self.x` a node class reads is assigned somewhere in that class.

Hardware-only paths (drive_node's bus thread, panel_node's Modbus loop) never
run in simulation, so a read of an attribute that was never created only shows
up on the vehicle - where it took the base down on the first unified-service
boot (drive_node `_cursor`, 2026-09-16). This is a static check, not a
substitute for running the code.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2]
# rclpy.Node methods and attributes used through self.
NODE_API = {
    "get_logger",
    "get_parameter",
    "get_parameters",
    "declare_parameter",
    "get_clock",
    "create_publisher",
    "create_subscription",
    "create_service",
    "create_client",
    "create_timer",
    "create_rate",
    "create_guard_condition",
    "destroy_node",
    "destroy_timer",
    "destroy_publisher",
    "destroy_subscription",
    "destroy_client",
    "destroy_service",
    "get_name",
    "get_namespace",
    "count_publishers",
    "count_subscribers",
    "executor",
    "context",
    "handle",
    "get_topic_names_and_types",
    "get_node_names",
    "set_parameters",
    "add_on_set_parameters_callback",
}


def _lean_api() -> set[str]:
    """Methods and attributes every LeanNode subclass inherits from amr_base/lean_node.py."""
    tree = ast.parse((SRC / "amr_base" / "amr_base" / "lean_node.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LeanNode")
    out = set()
    for n in ast.walk(cls):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(n.name)
        elif isinstance(n, ast.Attribute) and _is_self_attr(n) and isinstance(n.ctx, ast.Store):
            out.add(n.attr)
    return out


def _is_self_attr(n: ast.AST) -> bool:
    return isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"


def _classes(source: str) -> list[tuple[str, set, dict, list]]:
    """(name, assigned, used {attr: line}, base names) for every class in one source."""
    out = []
    for cls in (n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef)):
        assigned, used = set(), {}
        for n in ast.walk(cls):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assigned.add(n.name)
            elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for tgt in n.targets if isinstance(n, ast.Assign) else [n.target]:
                    for e in ast.walk(tgt):
                        if _is_self_attr(e):
                            assigned.add(e.attr)
                        elif isinstance(e, ast.Name):
                            assigned.add(e.id)  # class-level attributes
            if _is_self_attr(n) and isinstance(n.ctx, ast.Load):
                used.setdefault(n.attr, n.lineno)
        bases = [b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "") for b in cls.bases]
        out.append((cls.name, assigned, used, bases))
    return out


def _inherited(name: str, index: dict, seen: set | None = None) -> set:
    """What a class and its bases assign, for bases defined in the scanned sources (SiteRun is
    a TapeRun from another module, 2026-11-16: its reads of TapeRun's state are not bugs).
    A base from outside the scan adds nothing, so the check stays strict there."""
    seen = set() if seen is None else seen
    if name in seen:
        return set()
    seen.add(name)
    out = set()
    for assigned, bases in index.get(name, ()):
        out |= assigned
        for b in bases:
            out |= _inherited(b, index, seen)
    return out


def _problems(sources: dict) -> list[str]:
    """sources: {label: text} -> 'label:line Class.attr' for every read never assigned."""
    found = {label: _classes(text) for label, text in sources.items()}
    index: dict = {}
    for rows in found.values():
        for name, assigned, _, bases in rows:
            index.setdefault(name, []).append((assigned, bases))
    out = []
    for label, rows in found.items():
        for name, _, used, _ in rows:
            assigned = set(NODE_API) | LEAN_API | _inherited(name, index)
            out += [f"{label}:{line} {name}.{a}" for a, line in used.items() if a not in assigned]
    return out


LEAN_API = _lean_api()


def test_no_node_reads_an_attribute_it_never_assigns():
    files = sorted(SRC.glob("amr_*/amr_*/*.py"))
    assert files, f"no package sources under {SRC}"
    problems = _problems({str(f.relative_to(SRC)): f.read_text() for f in files})
    assert not problems, "read but never assigned:\n" + "\n".join(problems)


def test_a_subclass_still_gets_caught_reading_what_neither_class_assigns():
    """Following the bases must not make the check blind: only what a base assigns is excused."""
    base = "class Base:\n    def __init__(self):\n        self.a = 1\n"
    sub = ("from base import Base\n\nclass Sub(Base):\n    def f(self):\n"
           "        return self.a + self.b\n")
    assert _problems({"base.py": base, "sub.py": sub}) == ["sub.py:5 Sub.b"]
