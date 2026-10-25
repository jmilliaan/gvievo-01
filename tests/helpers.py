"""Shared rig for the offline suite. No CAN, no hardware, no motion.

The line-following plant lives with LINE mode now: amr_ws/src/amr_line/test/harness.py
(the ported rig, with its negative control) and amr_sim/amr_sim/tape_plant.py (the
sim tape). This module only counts checks.

FAIL is shared state, deliberately. Every module appends to the same list so
run_all.py can report one verdict for the whole suite rather than eight.
"""
import pathlib
import sys

# Repo root, so a check that reads a source file keeps working wherever the
# suite is run from and wherever the module it inspects has been moved to.
ROOT = pathlib.Path(__file__).resolve().parent.parent
# The repo root, so `agv_core` resolves however the
# suite was started: run_all.py, `pytest tests/test_x.py`, or a single module
# run directly. Nothing else goes on the path - the layer directories that used
# to be inserted here are a package now.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Re-exported, not used here: run_all.py prints the loaded profile as
# helpers.config, and several modules reach it the same way. Importing it here
# is also what proves the path above works before any test runs.
from agv_core import config  # noqa: E402,F401,I001


FAIL = []

# Counted so run_all.py can pin the total. A single-element list rather than an
# int because every test module imports this by value.
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def _why(g, index, value=0x40, sub=None):
    """The refusal message, so a test can assert it explains itself."""
    try:
        g.check(index, value, sub)
        return ""
    except g.ForbiddenWrite as e:
        return str(e)
