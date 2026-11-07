"""The fixed start of LineState.home_detail while a position check runs (manuals/home-auto-confirm-plan.md).

line_follow_node writes these and the Home page reads them, so the two cannot drift. No message change was
wanted for a status line: a detail after the prefix is for people.
"""

CHECKING = "Checking position"
FAILED = "Position check failed"
RECHECKING = "Position lost, rechecking at home"
