"""Test doubles the amr_web tests share (lean plan D19). Not shared across packages."""


class Clock:
    """A monotonic clock a test moves by hand: clock.t += dt."""

    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t
