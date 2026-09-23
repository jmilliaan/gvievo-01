"""The DEMO page's live panel: a vehicle on display, explained to visitors.

The audience is purchasing, plant management and people shopping for material
handling - not engineers. So the whole vocabulary is the five sentences below,
decided HERE, on the server. The browser never receives a fault code, a reason
string, a hold cause or a hex number, and a test scans the output for them.

*** A fault reads as "standing by", on purpose. *** This page diagnoses nothing.
The operator's Home page still tells the truth; this one only has to avoid a red
screen in front of a customer.

Pure: no Flask, no rclpy. `view()` takes the dict `adapter.state()` returns.
"""

from __future__ import annotations

from dataclasses import dataclass

DRIVING, WAITING, READY, PAUSED, STANDBY = "driving", "waiting", "ready", "paused", "standby"

SENTENCES = {
    DRIVING: "Driving the route",
    WAITING: "Someone is in the way. It waits, then continues by itself.",
    READY: "Ready. Press Start on the vehicle to begin.",
    PAUSED: "Paused between runs",
    STANDBY: "Standing by for the next demonstration",
}

MODE_TEXT = {"LINE": "Tape guided", "NAVIGATION": "Tape-free"}

# Older than this, a layer's state is not evidence of anything.
FRESH_S = 2.0
# A gap between polls longer than this adds no distance: nobody saw the speed then.
MAX_STEP_S = 2.0


@dataclass
class Counters:
    """What the demo has shown since it started. Lives as long as the web process
    (or until /demo?reset=1)."""

    distance_m: float = 0.0
    safety_stops: int = 0
    last_t: float | None = None
    in_field_hold: bool = False

    def reset(self) -> None:
        self.distance_m, self.safety_stops = 0.0, 0
        self.last_t, self.in_field_hold = None, False


def _fresh(d: dict | None, stale: bool = False) -> dict | None:
    if not d or stale:
        return None
    age = d.get("age_s")
    if age is not None and age > FRESH_S:
        return None
    return d


def speed_mps(state: dict, wheel_radius_m: float) -> float:
    """Body speed from the mux's commanded wheel rates. A pivot reads 0, which is
    what a visitor sees too. Stale or missing = 0."""
    mux = _fresh(state.get("mux"))
    if not mux:
        return 0.0
    try:
        wl, wr = float(mux.get("left_rad_s") or 0.0), float(mux.get("right_rad_s") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    v = abs((wl + wr) / 2.0) * wheel_radius_m
    return v if v < 10.0 else 0.0  # nonsense is not shown


def status(state: dict) -> str:
    """One of the five. Order matters: a person in the field explains a stop better
    than anything else, so it is checked before faults and drive state."""
    mode = state.get("mode")
    if not mode:
        return STANDBY
    run = _fresh(state.get("run"), bool(state.get("run_stale")))
    line = _fresh(state.get("line"))
    rs = (run or {}).get("state_name", "")
    ls = (line or {}).get("state_name", "")

    if (rs == "BLOCKED" and (run or {}).get("hold_cause") == "field") or (
        ls == "HOLD" and (line or {}).get("hold_cause") == "field"
    ):
        return WAITING
    if "FAULT" in (rs, ls) or mode.get("mode_name") == "FAULT":
        return STANDBY
    drives = _fresh(state.get("drives"))
    if not drives or not drives.get("operational"):
        return STANDBY
    if rs == "EXECUTING" or ls == "RUNNING":
        return DRIVING
    if rs == "READY" or ls == "ARMED":
        return READY
    if rs in ("PAUSED", "BLOCKED", "DONE") or ls in ("HOLD", "DONE"):
        return PAUSED
    return STANDBY


def view(state: dict, wheel_radius_m: float, counters: Counters, now: float) -> dict:
    """The /api/demo body. Advances the counters by one poll."""
    st = status(state)
    v = speed_mps(state, wheel_radius_m) if st == DRIVING else 0.0

    if counters.last_t is not None:
        dt = now - counters.last_t
        if 0.0 < dt <= MAX_STEP_S:
            counters.distance_m += v * dt
    counters.last_t = now

    held = st == WAITING
    if held and not counters.in_field_hold:
        counters.safety_stops += 1
    counters.in_field_hold = held

    mode = (state.get("mode") or {}).get("mode_name", "")
    return {
        "status": st,
        "sentence": SENTENCES[st],
        "speed_mps": round(v, 2),
        "distance_m": round(counters.distance_m, 1),
        "safety_stops": counters.safety_stops,
        "mode": MODE_TEXT.get(mode, "Standing by"),
    }
