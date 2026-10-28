"""hold_policy: the hold texts, debounce and pre-move rules both run FSMs share (D15)."""

from amr_base import hold_policy as hp


def test_safety_hold_texts_are_the_operator_strings():
    assert hp.hold_text("field", "x") == "safety stop (protective field): x"
    assert hp.hold_text("estop", "x") == "safety stop (E-stop / safety chain): x"
    assert hp.hold_text("controller", "aborted") == "aborted"


def test_product_causes_extend_the_texts():
    extra = {"authority": "authority lost: {why}"}
    assert hp.hold_text("authority", "lease", extra) == "authority lost: lease"
    assert hp.hold_text("field", "x", extra) == "safety stop (protective field): x"
    assert hp.hold_text("authority", "lease") == "lease"


def test_only_the_field_resumes_by_itself():
    """Owner decision 2026-10-25 (unified plan WP-A2), both products."""
    assert hp.auto_causes(False) == ("field",)
    assert hp.auto_causes(True) == ("field", "estop")


def test_the_catalogue_agrees_with_the_policy():
    """clears_by == 'auto' exactly for the causes that resume by themselves. `pending` is the
    executor's few-hundred-ms classification of a wheel-feedback loss (it becomes a safety
    hold or a FAULT, never a resume), so its 'wait a moment' row stays auto."""
    from agv_core import alarms

    for cause, code in alarms.HOLD_CODES.items():
        if cause == "pending":
            continue
        auto = alarms.get(code).clears_by == "auto"
        assert auto == (cause in hp.AUTO_CAUSES), (cause, code)
    for cause in hp.SAFETY_CAUSES:
        assert cause in alarms.HOLD_CODES, cause


def test_every_device_cause_is_a_catalogue_cause():
    from agv_core import alarms

    assert set(hp.CAUSE_DEVICE) <= set(alarms.HOLD_CODES)
    assert hp.hold_device("field") == "scanner" and hp.hold_device("station") == ""


def test_debounce_needs_a_continuous_failure():
    d = hp.Debounce()
    assert not d.held(0.0, "stale", 0.5)
    assert not d.held(0.4, "other reason", 0.5)
    assert d.held(0.5, "stale", 0.5)
    assert not d.held(0.6, None, 0.5)
    assert d.since is None
    assert not d.held(0.7, "stale", 0.5)
    d.reset()
    assert d.since is None


def test_debounce_zero_grace_holds_at_once():
    assert hp.Debounce().held(3.0, "x", 0.0)


def test_premove_needs_time_and_torque():
    assert hp.premove_ready(2.0, 2.0, True, False)
    assert not hp.premove_ready(1.9, 2.0, True, False)
    assert not hp.premove_ready(5.0, 2.0, False, False)
    assert not hp.premove_ready(5.0, 2.0, True, True)


def test_premove_timeout_text():
    assert hp.premove_timeout_text(8.0, "tail") == "drives did not power up within 8 s (tail)"
