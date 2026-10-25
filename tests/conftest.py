"""pytest over the library suite (lean plan D26): check() records a failure in helpers.FAIL and
never raises, so a test run by pytest passed whatever it found. Fail the test instead."""

import helpers
import pytest


@pytest.fixture(autouse=True)
def _checks_must_pass():
    before = len(helpers.FAIL)
    yield
    new = helpers.FAIL[before:]
    assert not new, f"failed check(s): {new}"
