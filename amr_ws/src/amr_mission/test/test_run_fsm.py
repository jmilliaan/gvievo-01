from amr_mission import run_fsm as f


def loaded() -> f.RunFsm:
    m = f.RunFsm()
    assert m.load("m1", 3)
    return m


def test_load_only_when_idle_ready_or_done():
    m = loaded()
    assert m.state == f.READY
    assert m.start(auto=True, gate_ok=True)
    assert not m.load("m2", 1) and "cannot load" in m.reason
    m.step_done()
    m.step_done()
    m.step_done()
    assert m.state == f.DONE
    assert m.load("m2", 1) and m.state == f.READY and m.run_id == ""


def test_start_needs_auto_and_gate():
    m = loaded()
    assert not m.start(auto=False, gate_ok=True) and "AUTO" in m.reason
    assert not m.start(auto=True, gate_ok=False, gate_reason="0.3 m from route start") and "0.3 m" in m.reason
    assert m.state == f.READY
    assert m.start(auto=True, gate_ok=True)
    assert m.state == f.EXECUTING and m.step_index == 0 and m.run_id


def test_stale_run_ids_are_rejected():
    m = loaded()
    m.start(True, True)
    old = m.run_id
    assert m.accepts(old)
    assert not m.accepts("other") and not m.accepts("")
    m.abort("test")
    assert not m.accepts(old)
    m.load("m1", 3)
    m.start(True, True)
    assert m.run_id != old and not m.accepts(old)


def test_pause_prepare_resume_start():
    m = loaded()
    m.start(True, True)
    assert m.pause()
    assert m.state == f.PAUSED and not m.resume_prepared
    assert not m.start(True, True) and "not prepared" in m.reason
    assert not m.prepare_resume(False, "obstacle still there") and "refused" in m.reason
    assert m.prepare_resume(True, "")
    assert not m.start(auto=False, gate_ok=True)  # selector must be AUTO
    assert m.start(auto=True, gate_ok=True)
    assert m.state == f.EXECUTING and m.step_index == 0 and not m.resume_prepared


def test_prepared_resume_is_withdrawn_by_new_evidence():
    m = loaded()
    m.start(True, True)
    m.block("box on the line")
    assert m.state == f.BLOCKED
    m.prepare_resume(True, "")
    m.invalidate_resume("obstacle returned")
    assert not m.resume_prepared and not m.start(True, True)


def test_abort_and_manual_takeover_discard_the_run():
    m = loaded()
    m.start(True, True)
    m.step_done()
    assert m.abort("selector moved to MANUAL")
    assert m.state == f.IDLE and m.run_id == "" and m.step_index == -1
    assert not m.abort("again")


def test_fault_needs_ack_then_reload():
    m = loaded()
    m.start(True, True)
    assert m.fault("scan stale")
    assert m.state == f.FAULT and not m.resume_prepared
    assert not m.start(True, True)
    assert not m.load("m1", 3)
    assert not m.prepare_resume(True, "")
    assert m.ack() and m.state == f.IDLE
    assert not m.ack()
    assert m.load("m1", 3)


def test_unready_from_ready_only():
    m = loaded()
    assert m.unready("localisation LOST") and m.state == f.IDLE
    m.load("m1", 3)
    m.start(True, True)
    assert not m.unready("x") and m.state == f.EXECUTING


def test_step_progress_to_done():
    m = loaded()
    m.start(True, True)
    assert m.step_done() and m.step_index == 1 and m.state == f.EXECUTING
    m.step_done()
    assert m.step_done() and m.state == f.DONE
    assert not m.step_done()
    assert not m.pause() and not m.block("x")
