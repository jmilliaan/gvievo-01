#!/usr/bin/env python3
"""Fault injection (plan phase 3.6): kill something, then read the operator surface.

Opt-in (AMR_SIM_TESTS=1). For each injected failure this asserts the three things
the plan asks for, in the operator's terms rather than the log's:

  1. the expected CODE stands on /api/alarms within 2 s,
  2. the event is on DISK (so it survives the restart that follows),
  3. the surface offers the DOCUMENTED button for that code.

The web app runs in-process here (Flask test client over a real RosAdapter on the
sim domain) rather than as a port: the endpoint under test is the real one, and no
socket collides with the vehicle's own service on 5001.

A mechanism check, per the repo's rule for sim tests: it asserts that the chain
node -> event -> catalogue -> button exists, never how fast the sim drives.

Sensor dropouts (hardening plan H-P3-3, unified plan WP-T3, 2026-11-16), through the sim fault
hooks (amr_sim.fault_hooks, WP-T2) on a LINE run over tape_synth, with AMR_SIM_FIELDS=1 so the
mux and the follower read fake_output_paths' /output_paths instead of assuming the field clear:
  tape dropout     tape_synth ~/mute: HOLD `sensor`, zero, no resume until a fresh Start
  field stream     /output_paths dropped: FIELD_UNKNOWN zero within the field freshness limit,
                   no AUTO after the stream is back until a fresh Start
  stale panel      fake_panel ~/invalid and ~/mute: the rows and the hold name the panel
  silent drive     fake_base ~/drive_silent: DRIVE_SILENT (power cycle), no DRIVES_NOT_READY
Not here: the IMU drop (its operator row is drive_node's DeviceHealth mls_gyro, hardware only;
LINE falls back to the wheels' yaw by design) and the RFID drop (decision 23: RFID not used).
Run once per milestone, sequentially, never while amr.service runs (port 5001, the CAN bus).
"""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

if os.environ.get("AMR_SIM_TESTS") != "1":
    pytest.skip("simulation fault-injection test; set AMR_SIM_TESTS=1", allow_module_level=True)
os.environ["ROS_DOMAIN_ID"] = "69"
os.environ["AMR_SUPERVISOR_SIM"] = "1"
os.environ["AMR_SIM_FIELDS"] = "1"  # WP-T2: fake_output_paths in the sim base, read by mux + follower

import threading  # noqa: E402

import rclpy  # noqa: E402
import rclpy.executors  # noqa: E402
from agv_core import alarms as cat  # noqa: E402
from agv_core import config  # noqa: E402
from std_srvs.srv import SetBool, Trigger  # noqa: E402

from amr_base.qos import LATCHED, RELIABLE_1  # noqa: E402
from amr_interfaces.msg import LineState, ModeState, MuxState, WheelVelocities  # noqa: E402
from amr_interfaces.srv import LineTeach, SelectMission  # noqa: E402

SETTLE_S = 2.0  # the plan's budget: a code must reach the operator within this
LINE_MODE = 7  # ModeState LINE (wire.MODE_NAMES)
ZERO_RAD_S = 1e-3
# The fault hooks the dropout cases call (amr_sim/test/test_fault_hooks.py checks each one exists).
HOOKS = {
    "tape_mute": "/tape_synth/mute",
    "panel_mute": "/fake_panel/mute",
    "panel_invalid": "/fake_panel/invalid",
    "drive_silent": "/fake_base/drive_silent",
}


@pytest.fixture(scope="module")
def surface(tmp_path_factory):
    """The sim stack plus the real web app over it, and the on-disk event log."""
    state = tmp_path_factory.mktemp("fi_state")
    maps = state / "maps"
    maps.mkdir()
    (state / "logs").mkdir()
    os.environ["AMR_STATE_DIR"] = str(state)
    # The MLS for the LINE run (H-P3-3): no launch file starts it. Long tape, so no run ends on it.
    tape = subprocess.Popen(
        [sys.executable, "-m", "amr_sim.tape_synth_node", "--ros-args", "-p", "tape_length_m:=500.0"],
        stdout=open(state / "tape_synth.log", "wb"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "amr_bringup.supervisor_node", "--ros-args",
            "-p", "real:=false", "-p", "web:=false",
            "-p", f"state_dir:={state}", "-p", f"maps_dir:={maps}",
        ],
        stdout=open(state / "supervisor.log", "wb"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    rclpy.init()
    from amr_web.adapter import RosAdapter, start_spinning  # noqa: PLC0415
    from amr_web.server import create_app  # noqa: PLC0415

    adapter = RosAdapter()
    spinner = start_spinning(adapter)
    app = create_app(adapter, str(maps), state_dir=str(state))
    app.config["TESTING"] = True
    client = app.test_client()
    yield client, adapter, proc, state
    spinner.stop()
    try:
        adapter.destroy_node()
    except Exception:  # noqa: BLE001
        pass
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=40)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        os.killpg(tape.pid, signal.SIGKILL)
    rclpy.shutdown()


class Probe:
    """The test's own ROS node: the line, the mux and the wheel command, and the fault hooks."""

    def __init__(self):
        self.node = rclpy.create_node("fi_probe")
        self.lock = threading.Lock()
        self.line = self.mux = self.mode = None
        self.wheel = (0.0, 0.0)
        self.zero_since = None  # when the current run of zero /cmd_wheel_vel began (monotonic)
        n = self.node
        n.create_subscription(LineState, "/amr/line_state", self._keep("line"), LATCHED)
        n.create_subscription(ModeState, "/amr/mode_state", self._keep("mode"), LATCHED)
        n.create_subscription(MuxState, "/amr/mux_state", self._keep("mux"), RELIABLE_1)
        n.create_subscription(WheelVelocities, "/cmd_wheel_vel", self._on_wheel, RELIABLE_1)
        services = {
            "auto": (SetBool, "/sim/panel/set_mode"),
            "start": (Trigger, "/sim/panel/press_start"),
            "reset": (Trigger, "/sim/panel/press_reset"),
            "mission": (SelectMission, "/amr/line/mission"),
            "fields": (LineTeach, "/sim/output_paths/set"),
            **{k: (SetBool, v) for k, v in HOOKS.items()},
        }
        self.cli = {k: n.create_client(srv, topic) for k, (srv, topic) in services.items()}
        self.executor = rclpy.executors.SingleThreadedExecutor()
        self.executor.add_node(n)
        threading.Thread(target=self.executor.spin, daemon=True).start()

    def _keep(self, attr):
        def cb(m):
            with self.lock:
                setattr(self, attr, m)
        return cb

    def _on_wheel(self, m):
        with self.lock:
            self.wheel = (m.left_rad_s, m.right_rad_s)
            if self.moving():
                self.zero_since = None
            elif self.zero_since is None:
                self.zero_since = time.monotonic()

    def moving(self) -> bool:
        return max(abs(self.wheel[0]), abs(self.wheel[1])) > ZERO_RAD_S

    def call(self, name, req=None, timeout=10.0):
        c = self.cli[name]
        assert c.wait_for_service(timeout_sec=90.0), f"{c.srv_name} unavailable"  # a booting base
        fut = c.call_async(req if req is not None else c.srv_type.Request())
        deadline = time.monotonic() + timeout
        while not fut.done():
            assert time.monotonic() < deadline, f"{c.srv_name} timed out"
            time.sleep(0.02)
        return fut.result()

    def hook(self, name, on: bool):
        r = self.call(name, SetBool.Request(data=on))
        assert r.success, r.message

    def fields(self, action: str):
        r = self.call("fields", LineTeach.Request(action=action, arg=""))
        assert r.ok, r.message

    def line_text(self) -> str:
        with self.lock:
            m = self.line
        if m is None:
            return "no LineState"
        return f"state {m.state} cause {m.hold_cause!r} code {m.code!r}: {m.message}"

    def wait(self, pred, timeout, what) -> float:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            with self.lock:
                if pred():
                    return time.monotonic() - t0
            time.sleep(0.02)
        mux = self.mux.code if self.mux is not None else None
        raise AssertionError(f"timeout ({timeout} s): {what}; line {self.line_text()}; mux {mux!r}")

    def wait_line(self, state, timeout, what=""):
        return self.wait(lambda: self.line is not None and self.line.state == state, timeout,
                         what or f"LineState {state}")

    def start_run(self):
        """LINE, plain line following, AUTO, physical Start -> RUNNING with the wheels turning."""
        self.wait(lambda: self.mode is not None and self.mode.mode == LINE_MODE, 90, "LINE mode")
        self.wait_line(LineState.IDLE, 10, "line layer IDLE")
        r = self.call("mission", SelectMission.Request(name="none", destination=""))
        assert r.ok, r.message  # plain line following: no site trip, no RFID tags needed
        self.hook("auto", True)
        time.sleep(0.5)
        self.call("start")
        self.wait_line(LineState.RUNNING, 30, "RUNNING after Start (pre-move warning first)")
        self.wait(self.moving, 10, "wheels turning under LINE")

    def end_run(self):
        """Reset ends any run (O-3: outside IDLE, and not an estop hold); back to MANUAL."""
        self.call("reset")
        self.wait_line(LineState.IDLE, 10, "IDLE after Reset")
        self.hook("auto", False)
        self.wait(lambda: not self.moving(), 3, "zero after the run")


@pytest.fixture(scope="module")
def probe(surface):
    p = Probe()
    p.fields("clear")  # a known field for every case; a case that drops it puts it back
    yield p
    p.executor.shutdown()
    p.node.destroy_node()


def wait_for_code(client, code: str, timeout: float = SETTLE_S) -> dict:
    """The standing row for `code`, or an assertion naming what was standing instead."""
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        rows = client.get("/api/alarms").get_json()["alarms"]
        seen = [r["code"] for r in rows]
        for row in rows:
            if row["code"] == code:
                return row
        time.sleep(0.1)
    raise AssertionError(f"{code} never stood within {timeout} s; standing: {seen}")


def on_disk(state, code: str, timeout: float = SETTLE_S) -> bool:
    """The event log is what an engineer reads after a restart, so it is the record
    that matters - not the in-memory ring."""
    path = os.path.join(str(state), "logs", "events.jsonl")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        if json.loads(line).get("code") == code:
                            return True
                    except ValueError:
                        continue
        except OSError:
            pass
        time.sleep(0.1)
    return False


def test_a_healthy_sim_stands_nothing(surface, probe):
    client, _, _, _ = surface  # probe: the field is forced clear before this looks (WP-T3)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        d = client.get("/api/alarms").get_json()
        if d["headline"]["state"].startswith("READY"):
            assert d["alarms"] == [], d["alarms"]
            return
        time.sleep(0.5)
    raise AssertionError(f"never reached READY: {client.get('/api/alarms').get_json()}")


def test_the_boot_report_reaches_the_event_log(surface):
    _, _, _, state = surface
    assert on_disk(state, "BOOT_READY", timeout=5.0)


def test_tape_dropout_holds_sensor(surface, probe):
    """H-P3-3: the MLS goes silent while running -> HOLD `sensor`, zero, and nothing moves again
    until a fresh physical Start, however long the tape has been back (decision 1)."""
    client, _, _, _ = surface
    probe.start_run()
    probe.hook("tape_mute", True)
    try:
        probe.wait(lambda: probe.line.state == LineState.HOLD and probe.line.hold_cause == "sensor",
                   SETTLE_S, "HOLD sensor")
        probe.wait(lambda: not probe.moving(), 1.0, "zero after the MLS went silent")
        assert wait_for_code(client, cat.hold_code("sensor"))["clears_by"] == "start_button"
    finally:
        probe.hook("tape_mute", False)
    time.sleep(3.0)  # the tape is back: still held, still zero
    assert probe.line.state == LineState.HOLD, probe.line_text()
    assert not probe.moving()
    probe.call("start")
    probe.wait_line(LineState.RUNNING, 30, "RUNNING on the fresh Start")
    probe.end_run()


def test_field_stream_drop_stops_within_the_freshness_limit(surface, probe):
    """H-P3-3: /output_paths stops -> the mux zeroes LINE as FIELD_UNKNOWN within the field
    freshness limit (+0.1 s: the probe's latency and one mux tick); when the stream is back the
    follower stays held until a fresh Start."""
    client, _, _, _ = surface
    probe.start_run()
    probe.fields("drop")
    t0 = time.monotonic()
    try:
        probe.wait(lambda: probe.mux is not None and probe.mux.code == "FIELD_UNKNOWN", SETTLE_S,
                   "mux FIELD_UNKNOWN")
        probe.wait(lambda: probe.zero_since is not None, SETTLE_S, "zero /cmd_wheel_vel")
        dt = probe.zero_since - t0
        print(f"field stream dropped: wheel command zero after {dt * 1000:.0f} ms")
        assert dt <= config.FRESH_FIELD_S + 0.1, f"zero after {dt:.2f} s"
        # the follower's own view: field state unknown is a debounced prerequisite (`prereq`);
        # the mux's FIELD_UNKNOWN is not an inhibit, so the operator's row is the line's
        probe.wait(lambda: probe.line.state == LineState.HOLD, SETTLE_S, "follower holds")
        held = probe.line.hold_cause == "prereq" and "field" in probe.line.message.lower()
        assert held, probe.line_text()
        wait_for_code(client, cat.hold_code("prereq"))
    finally:
        probe.fields("clear")
    time.sleep(3.0)
    assert probe.line.state == LineState.HOLD, f"resumed without a Start: {probe.line_text()}"
    assert not probe.moving()
    probe.call("start")
    probe.wait_line(LineState.RUNNING, 30, "RUNNING on the fresh Start")
    probe.end_run()


def test_stale_panel_names_panel(surface, probe):
    """H-P3-3: an invalid panel image holds at once (`panel`) and a silent panel after the grace;
    both say "panel" to the operator, and neither resumes without a fresh Start."""
    client, _, _, _ = surface
    probe.start_run()
    probe.hook("panel_invalid", True)
    try:
        probe.wait(lambda: probe.line.state == LineState.HOLD and probe.line.hold_cause == "panel",
                   SETTLE_S, "HOLD panel (image invalid)")
        probe.wait(lambda: not probe.moving(), 1.0, "zero on the invalid panel image")
        assert "panel" in wait_for_code(client, "PANEL_STALE")["detail"]
        wait_for_code(client, cat.hold_code("panel"))
    finally:
        probe.hook("panel_invalid", False)
    time.sleep(2.0)
    assert probe.line.state == LineState.HOLD, f"resumed without a Start: {probe.line_text()}"
    probe.call("start")
    probe.wait_line(LineState.RUNNING, 30, "RUNNING on the fresh Start")
    probe.hook("panel_mute", True)
    try:
        probe.wait(lambda: probe.line.state == LineState.HOLD, SETTLE_S + 1.0, "HOLD on a silent panel")
        probe.wait(lambda: not probe.moving(), 1.0, "zero on a silent panel")
        assert "panel" in probe.line.message.lower(), probe.line_text()
        assert "panel" in wait_for_code(client, "PANEL_STALE")["detail"]
    finally:
        probe.hook("panel_mute", False)
    probe.end_run()


def test_silent_drive_offers_power_cycle(surface, probe):
    """H-P3-3: one drive stops answering -> the DRIVE_SILENT row (power cycle, then Recover),
    and no DRIVES_NOT_READY beside it: the drive row already says more (WP-B4)."""
    client, _, _, _ = surface
    probe.hook("drive_silent", True)
    try:
        row = wait_for_code(client, "DRIVE_SILENT")
        assert row["clears_by"] == "power_cycle" and cat.BUTTON["power_cycle"] == "Recover"
        time.sleep(1.0)  # the mux's own DRIVES_NOT_READY has had time to arrive
        codes = [r["code"] for r in client.get("/api/alarms").get_json()["alarms"]]
        assert "DRIVES_NOT_READY" not in codes, codes
    finally:
        probe.hook("drive_silent", False)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        codes = [r["code"] for r in client.get("/api/alarms").get_json()["alarms"]]
        if "DRIVE_SILENT" not in codes:
            break
        time.sleep(0.2)
    assert "DRIVE_SILENT" not in codes, codes


def test_killing_the_base_offers_restart_not_recover(surface):
    """A dead base cannot be rebuilt by Recover (the drives must be re-armed), so the
    operator surface must send them to Restart instead of a button that will refuse.
    Runs after the dropout cases: it ends the base. The event on disk is the supervisor's FAULT
    event, logged under the fault's own code with its reason since 2026-11-16 (WP-T3; it was
    "MODE_CHANGE ... -> FAULT: BASE_EXITED", without the node WP-H4 names)."""
    from test_unified_sim import BASE_PATTERN, kill_owned  # noqa: PLC0415

    client, _, proc, state = surface
    assert kill_owned(proc.pid, BASE_PATTERN), "nothing to kill: the base was not running"
    row = wait_for_code(client, "BASE_EXITED", timeout=15.0)
    assert row["clears_by"] == "restart_service"
    assert cat.BUTTON[row["clears_by"]] == "Restart"
    assert client.get("/api/alarms").get_json()["headline"]["button"] == "Restart"
    assert on_disk(state, "BASE_EXITED", timeout=5.0)
    # and the surface says NEEDS SERVICE, in those words
    assert client.get("/api/alarms").get_json()["headline"]["state"] == "NEEDS SERVICE"


def test_the_standing_row_carries_the_engineers_detail_too(surface):
    client, _, _, _ = surface
    row = wait_for_code(client, "BASE_EXITED", timeout=5.0)
    assert row["detail"] and row["hint"]
    assert row["title"] != row["detail"]  # the operator's words are not the log line
