"""At home from the panel: Start and Reset held together for HOLD_S, selector MANUAL (2026-11-11).
Pure and clock-fed: monotonic seconds in, one "fire" out per hold.

The same press as the web's At home (line_follow_node._at_home), by a person at the vehicle:

    MANUAL     only. Under AUTO a Start press is a motion command on its own (a trip from HOME, a
               resume), acted on at its edge, long before a 1 s hold could say it was meant as At home
    edges      a button counts only from its own rising edge on a valid image: a level held since the
               baseline (a button tied down or stuck at power-up, panel.PanelScan hazard 2) never does
    once       one fire per hold; both buttons are let go before the next can start
    anything   the panel invalid or stale, the selector at AUTO, either button released: start over

It decides nothing about motion: the caller makes the At home request, which the line node refuses
in a job that is running, with wheels moving, or under AUTO with station calling on.
"""

HOLD_S = 1.0


class HomeCombo:
    def __init__(self, hold_s=HOLD_S):
        self.hold_s = float(hold_s)
        self._since = {"start": None, "reset": None}    # rising edge time while still held
        self._fired = False

    def clear(self):
        self._since = {"start": None, "reset": None}

    def tick(self, now, valid, auto, start_held, reset_held, start_edge, reset_edge):
        """One panel message. True once, when both have been held together for hold_s."""
        if not valid or auto:
            self.clear()
            self._fired = False if not (start_held or reset_held) else self._fired
            return False
        for name, held, edge in (("start", start_held, start_edge), ("reset", reset_held, reset_edge)):
            if not held:
                self._since[name] = None
            elif edge and self._since[name] is None:
                self._since[name] = float(now)
        if not start_held and not reset_held:
            self._fired = False
        if self._fired or None in self._since.values():
            return False
        if now - max(self._since.values()) >= self.hold_s:
            self._fired = True
            return True
        return False

    def holding(self, now):
        """Seconds both have been held together so far, None when not (for the log)."""
        if self._fired or None in self._since.values():
            return None
        return now - max(self._since.values())
