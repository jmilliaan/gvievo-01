"""Test doubles the amr_bringup tests share (lean plan D19). Not shared across packages."""


class Log:
    """A logger that says nothing: get_logger = Log, then .info/.warn/.error(...)."""

    def info(self, *_):
        pass

    warn = error = debug = info
