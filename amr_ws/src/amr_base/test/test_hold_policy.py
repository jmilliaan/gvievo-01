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


def test_auto_causes_add_estop_only_when_allowed():
    assert hp.auto_causes(("field", "controller"), False) == ("field", "controller")
    assert hp.auto_causes(("field",), True) == ("field", "estop")


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
