"""The operator event log: moved to agv_core/eventlog.py (2026-11-16, unified plan WP-H3) so the
base's event recorder shares it without importing the web. Re-exported here unchanged."""

from agv_core.eventlog import KEEP, MAX_BYTES, EventLog, EventRing  # noqa: F401
