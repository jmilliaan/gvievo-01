"""line_follow_node (dual-product plan, Increment 1): magnetic-tape following.

    /amr/line/clear      Trigger            abort a running follow (back to IDLE)
    /amr/line/mission    SelectMission      the next run's job: mission + destination
    /amr/line_state      LineState          latched, on change + 1 Hz
    /amr/line_cmd        Twist              body command while following,
                                            to the mux's LINE source
    /amr/line_track      LineTrack  (in)    the MLS reading from drive_node
    /amr/line/teach      LineTeach          tape-graph teaching (tracked plan 3, P1; engineer)
    /amr/line/at_home    Trigger            parked at HOME-N: /initialpose from its taught pose
    /amcl_pose, /amr/localization_state (in) AMCL and readiness, when the layer runs them

Tape localization (tracked plan 3, 4): amr_line.tape_runtime teaches, and shadows unless
tape_loc.live; with tape_loc.live the site mission is the job and trips drive from its position
(amr_line.site_run).

With station.enabled only (manuals/station-call-plan.md), and none of it created otherwise:
    /amr/line/order        LineTeach    the MQTT bridge's depart / cancel; latches one request
    /amr/line/order_state  OrderState   latched, on change + 1 Hz
    /amr/rear/trolley      TrolleyState (in) the rear lidar; older than the field's freshness = unknown

There is no software arm (2026-10-07): the physical Start from IDLE checks the
prerequisites and runs in one step (FollowJob._start). Motor arming is drive_node's.

The vehicle follows only on a fresh physical Start edge - or, with station.enabled, leaving
HOME once on an accepted station order (FollowJob._order_start) - under a valid AUTO
panel, while the supervisor's lease carries LEASE_LINE - which it grants
EXCLUSIVELY in LINE mode, so no browser jog and no pendant can fight the tape.
Every tick re-checks that authority; the mux and the drive owner gate the
output again on their own.

*** The control law is not in this file. *** `amr_line.autopilot` is a
byte-for-byte port of the engine that ran this vehicle as a tape AGV, and
`amr_line.job` holds the authority state machine, ROS-free and unit-tested.
This node marshals messages, stamps freshness and owns the clock. Keep it that
way: the decisions worth testing must stay where a test can reach them without
a ROS graph.

*** Command shape: a body Twist, not per-wheel. *** The follower computes
(v, omega) internally and only converts to wheels at the end, so publishing
the body pair costs one exact round trip - kinematics.wheels_to_body and
body_to_wheels both apply the invert_left/invert_right rule, so it cancels -
and it puts LINE on the same accel path the mux already gives FOLLOW.
"""

from __future__ import annotations

import collections
import math
import os
import time

from agv_core import alarms, kinematics, paths
from agv_core import config as vehicle_config
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Imu
from std_srvs.srv import Trigger

from amr_base import drive_state, gating, hold_policy
from amr_base.lean_node import LeanNode, run
from amr_base.qos import EVENT_STREAM, LATCHED, RELIABLE_1
from amr_base.qos import SENSOR_DATA as SENSOR
from amr_interfaces.msg import (
    ControlLease,
    DriveStatus,
    Event,
    LineState,
    LineTrack,
    LocalizationState,
    MarkerEvent,
    ModeState,
    MuxState,
    PanelState,
    StationDetection,
    WheelStates,
)
from amr_interfaces.srv import LineTeach, SelectMission
from amr_line import (
    autopilot,
    flight_recorder,
    home_combo,
    position_confirm,
    rfid_intake,
    runtime,
    tape_health,
    trip_log,
)
from amr_line import job as lj
from amr_line import track as tk

try:
    # The protective field's real state comes from the SICK driver, the same
    # source and the same index the executor uses. Optional exactly as it is
    # there: the package is absent on a dev box, and a layer that cannot be
    # imported without the scanner driver cannot be unit-tested at all.
    from sick_safetyscanners2_interfaces.msg import OutputPaths
except ImportError:  # pragma: no cover - present on the vehicle
    OutputPaths = None


# The state machine's constants are LineState's constants. If a renumbering
# ever slips through, fail here at construction rather than let readiness.py's
# `line_state in (1, 2, 3)` quietly stop guarding a moving vehicle.
_WIRE = (
    (lj.IDLE, LineState.IDLE), (lj.ARMED, LineState.ARMED),
    (lj.RUNNING, LineState.RUNNING), (lj.HOLD, LineState.HOLD),
    (lj.DONE, LineState.DONE), (lj.FAULT, LineState.FAULT),
)


class LineFollowNode(LeanNode):
    def __init__(self) -> None:
        super().__init__("line_follow_node")
        for mine, wire in _WIRE:
            if mine != wire:
                raise RuntimeError(
                    f"amr_line.job state {mine} does not match LineState {wire}: "
                    "readiness._line_active_locked depends on ARMED/RUNNING/HOLD "
                    "being 1..3. Fix the message or the module, not this check."
                )

        self.declare_parameter("rate_hz", 50.0)
        self.declare_parameter("generation", 0)
        self.declare_parameter("prereq_grace_s", 0.5)
        # -1 = the profile's auto_resume_hold_s; a value here overrides it.
        self.declare_parameter("auto_resume_clear_s", -1.0)
        self.declare_parameter("auto_resume_estop", False)
        self.declare_parameter("accept_sdo_track", False)
        # Pinned at or above the mux's own limits by the profile (freshness.line_*, WP-A10).
        self.declare_parameter("panel_fresh_s", vehicle_config.FRESH_LINE_PANEL_S)
        self.declare_parameter("lease_fresh_s", vehicle_config.FRESH_LINE_LEASE_S)
        self.declare_parameter("drives_fresh_s", vehicle_config.FRESH_LINE_DRIVES_S)
        self.declare_parameter("field_output_index", 0)  # /output_paths status[i]
        # "scanner": the protective field is what a FRESH /output_paths says,
        # and unknown otherwise (a Start is refused and a torque loss is
        # an E-stop). "assume_clear": the sim, which has no scanner. The launch
        # file picks by the supervisor's `real`; never assume on a vehicle.
        self.declare_parameter("field_source", "scanner")
        self.declare_parameter("field_fresh_s", vehicle_config.FRESH_FIELD_S)  # /output_paths: every scan
        # Mission engine inputs (2026-10-02)
        self.declare_parameter("rfid_fresh_s", 1.5)  # heartbeat is 2 Hz
        self.declare_parameter("wheels_fresh_s", 0.1)
        self.declare_parameter("still_wheel_rad_s", 0.02)
        # Speed engine inputs (tracked-speed-plan-1, 2026-10-08): the curve guard's yaw
        # rate and speed, and the mux's warning-field factor for the U-turn budget.
        self.declare_parameter("imu_fresh_s", 0.1)
        self.declare_parameter("odom_fresh_s", 0.1)
        self.declare_parameter("mux_fresh_s", 0.3)  # /amr/mux_state is 10 Hz
        # Tape localization (tracked plan 3): set by line_layer.launch.py from the profile's
        # tape_loc block and the active pointer ($AMR_STATE_DIR/line_graph.json).
        self.declare_parameter("loc_status", "off: tape_loc.enabled is false")
        self.declare_parameter("loc_map_id", "")
        self.declare_parameter("loc_map_revision", -1)
        self.declare_parameter("loc_graph_revision", -1)
        self.declare_parameter("maps_dir", paths.maps_dir())
        self.declare_parameter("state_dir", paths.state_dir())

        self.dt = 1.0 / float(self.get_parameter("rate_hz").value)
        self._generation = int(self.get_parameter("generation").value)
        self.panel_fresh = float(self.get_parameter("panel_fresh_s").value)
        self.lease_fresh = float(self.get_parameter("lease_fresh_s").value)
        self.drives_fresh_s = float(self.get_parameter("drives_fresh_s").value)
        self.field_index = int(self.get_parameter("field_output_index").value)
        if self.field_index < 0:
            raise ValueError(f"field_output_index {self.field_index} < 0")
        self.field_source = str(self.get_parameter("field_source").value)
        if self.field_source not in ("scanner", "assume_clear"):
            raise ValueError(f"field_source {self.field_source!r}: scanner or assume_clear")
        self.field_fresh = float(self.get_parameter("field_fresh_s").value)

        # The engine is handed its constants; it never reads a profile itself.
        # `runtime` carries ONLY the names the engine reads. The layer's own
        # settings (rate floor, auto-resume window) come straight from the
        # profile: a getattr-with-default on `runtime` silently read 40 Hz
        # whatever the profile said (review finding 2026-09-21, F06).
        runtime.load_from_profile()
        auto_clear = float(self.get_parameter("auto_resume_clear_s").value)
        if auto_clear < 0:
            auto_clear = float(vehicle_config.AUTO_RESUME_HOLD_S)
        self.job = lj.FollowJob(
            autopilot.LineFollower(),
            prereq_grace_s=float(self.get_parameter("prereq_grace_s").value),
            auto_resume_clear_s=auto_clear,
            auto_resume_estop=bool(self.get_parameter("auto_resume_estop").value),
            premove_s=float(vehicle_config.AUTO_START_DELAY_S),
            premove_timeout_s=float(vehicle_config.PREMOVE_TIMEOUT_S),
            calling=bool(vehicle_config.STATION_ENABLED),
            no_trolley_run=bool(vehicle_config.STATION_NO_TROLLEY_RUN),
            settle_s=float(vehicle_config.STATION_SETTLE_S),
            holdoff_s=float(vehicle_config.STATION_HOLDOFF_S),
            order_torque_wait_s=float(vehicle_config.STATION_ORDER_TORQUE_WAIT_S),
        )
        # No job yet is plain line following, with the site's U-turn tags.
        _ok, msg = self.job.set_mission(self._plain_mission())
        self.get_logger().info(f"mission at start: {msg}")
        self.reader = tk.TrackReader(
            timeout_s=runtime.SENSOR_TIMEOUT_S,
            min_hz=float(vehicle_config.LINE_MIN_TRACK_HZ),
            accept_sdo=bool(self.get_parameter("accept_sdo_track").value),
        )

        self._panel = None
        self._panel_t = None
        self._start_edge_t = None
        self._reset_edge = False
        self._home_combo = home_combo.HomeCombo()
        self._lease = None
        self._lease_t = None
        self._drives_t = None
        self._torque_off_msg = False
        self._drive_link, self._drives_operational = "", False
        self._field_clear: bool | None = None  # last /output_paths verdict
        self._field_t: float | None = None     # ...and when it arrived (monotonic)
        self._t_last = time.monotonic()
        self._published_zero = True
        # RFID: the encounter stream rebuilt as the driver's snapshot shape.
        self.rfid_fresh = float(self.get_parameter("rfid_fresh_s").value)
        self.rfid_in = rfid_intake.RfidIntake(self.rfid_fresh)
        # MLS markers (mls-marker-plan 6): the same snapshot shape, rebuilt from /amr/line_marker.
        self._marker_t: float | None = None
        self._marker_status = {"ok": False, "status": "no marker data", "generation": None, "base": 0}
        self._marker_events: collections.deque = collections.deque(maxlen=64)
        # wheels: encoder counts for the U-turn and a stillness test
        self.wheels_fresh = float(self.get_parameter("wheels_fresh_s").value)
        self.still_w = float(self.get_parameter("still_wheel_rad_s").value)
        self._wheels: WheelStates | None = None
        self._wheels_t: float | None = None
        self.imu_fresh = float(self.get_parameter("imu_fresh_s").value)
        self.odom_fresh = float(self.get_parameter("odom_fresh_s").value)
        self.mux_fresh = float(self.get_parameter("mux_fresh_s").value)
        self._imu_wz: float | None = None
        self._imu_t: float | None = None
        self._odom: tuple[float, float] | None = None  # (v, wz)
        self._odom_t: float | None = None
        self._mux_scale = 1.0
        self._mux_t: float | None = None

        self.create_subscription(LineTrack, "/amr/line_track", self._on_track, SENSOR)
        self.create_subscription(PanelState, "/amr/panel_state", self._on_panel, 10)
        self.create_subscription(ControlLease, "/amr/control_lease", self._on_lease, RELIABLE_1)
        self.create_subscription(ModeState, "/amr/mode_state", self._on_mode, LATCHED)
        self.create_subscription(DriveStatus, "/drives/status", self._on_drives, RELIABLE_1)
        # Every RFID encounter and every marker is a message; a replay is never new.
        self.create_subscription(StationDetection, "/amr/rfid", self._on_rfid, EVENT_STREAM)
        self.create_subscription(MarkerEvent, "/amr/line_marker", self._on_marker, EVENT_STREAM)
        self.create_subscription(WheelStates, "/wheel_states", self._on_wheels, SENSOR)
        self.create_subscription(Imu, "/imu/data", self._on_imu, SENSOR)
        self.create_subscription(Odometry, "/odom_raw", self._on_odom, SENSOR)
        self.create_subscription(MuxState, "/amr/mux_state", self._on_mux, RELIABLE_1)
        if self.field_source == "assume_clear":
            self.get_logger().warning(
                "field_source=assume_clear: the protective field is ASSUMED clear "
                "(simulation contract). Never run a vehicle like this."
            )
        elif OutputPaths is not None:
            self.create_subscription(OutputPaths, "/output_paths", self._on_output_paths, SENSOR)
        else:
            self.get_logger().error(
                "sick_safetyscanners2_interfaces is not installed: the protective "
                "field stays UNKNOWN and this layer will not start. Install the "
                "scanner driver, or launch with field_source:=assume_clear in a sim."
            )

        self._pub_cmd = self.create_publisher(Twist, "/amr/line_cmd", RELIABLE_1)
        self._pub_state = self.create_publisher(LineState, "/amr/line_state", LATCHED)
        # Operator events on LINE-STATE changes only: the tick runs at 50 Hz.
        self._pub_event = self.create_publisher(Event, "/amr/events", 50)
        self._event_seq = 0
        self._event_state: int | None = None
        self._power_published: bool | None = None  # LineState.drive_power last sent
        self._missing_fields: set[str] = set()  # mission_snapshot keys LineState lacks (stale build)

        self.create_service(Trigger, "/amr/line/clear", self._srv_clear)
        self.create_service(SelectMission, "/amr/line/mission", self._srv_mission)

        self.tapeloc = self._tape_runtime()
        # MLS track level per position along the taught tape (mls-diagnostics-plan M3): written
        # at the end of each run, only where the locator was HEALTHY. Display/maintenance only.
        self.tape_health = tape_health.TapeHealth()
        self._state_dir = os.path.expanduser(str(self.get_parameter("state_dir").value))
        # Tick-by-tick evidence for "why did it stop" (2026-10-24): ~15 s kept, written to
        # <state_dir>/logs/line_trace on a run end, a hold, a kink pivot, a finished U-turn.
        self.flight = flight_recorder.FlightRecorder(self._state_dir)
        self._fr_kinks = 0
        self._fr_corners = 0
        self._fr_uturn_done = None
        self._fr_forks = 0
        # The whole run (2026-11-06): every tick, pose and event, written off the control thread.
        self.triplog = trip_log.TripLog(self._state_dir)
        self._tl_tick = 0
        self._tl_ready = None
        self._tl_ready_t = 0.0
        self._tl_route = None
        self._tl_forks = trip_log.ForkCursor()
        self._tl_failed = False
        self._tl_inputs = None
        self._pub_initialpose = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", RELIABLE_1)
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._on_amcl,
                                 QoSProfile(depth=5, reliability=QoSReliabilityPolicy.RELIABLE,
                                            durability=QoSDurabilityPolicy.VOLATILE))
        self.create_subscription(LocalizationState, "/amr/localization_state", self._on_readiness, LATCHED)
        self.create_service(LineTeach, "/amr/line/teach", self._srv_teach)
        self.create_service(Trigger, "/amr/line/at_home", self._srv_at_home)
        self._position = position_confirm.PositionConfirm(
            position_confirm.Params.from_profile(vehicle_config, self.job.calling))
        self._monitor, self._monitor_t, self._amcl_pose, self._amcl_pose_t = None, None, None, None
        self._confirm_client = self.create_client(Trigger, "/amr/localization/confirm")
        # Trips (tracked plan 4): machine calls, and the operator's two confirmations. They form
        # and record; a trip from them moves only on AUTO + the physical Start at HOME (Run → Calls).
        self.create_service(LineTeach, "/amr/line/trip", self._srv_trip)
        self._site_live()
        self._station_setup()
        # Guided mission (2026-10-23): the engineer's branch order for the next fork. It only
        # chooses a tape; motion still needs AUTO + the physical Start. The web gates it by PIN.
        for side in ("left", "straight", "right"):
            self.create_service(Trigger, f"/amr/line/branch/{side}",
                                lambda req, res, side=side: self._trigger(
                                    f"branch order {side}", lambda: self.job.order_branch(side), res))
        # Its speed toggle (2026-10-24): HIGH lets the marker pair grant HIGH, NORMAL ignores
        # the zone codes and drops HIGH at once. It never starts or resumes a run.
        for level in ("normal", "high"):
            self.create_service(Trigger, f"/amr/line/speed/{level}",
                                lambda req, res, level=level: self._trigger(
                                    f"speed toggle {level}",
                                    lambda: self.job.select_speed(level == "high"), res))
        # Its forced U-turn (2026-10-24): the next tape end is the U-turn, strip or not. It only
        # changes what a tape end means to the running job; it never starts or resumes a run.
        for act in ("force", "cancel"):
            self.create_service(Trigger, f"/amr/line/uturn/{act}",
                                lambda req, res, act=act: self._trigger(
                                    f"forced U-turn {act}",
                                    lambda: self.job.force_u_turn(act == "force"), res))
        # And "continue this run on the next Start" after a "track lost" end (2026-10-24).
        for act in ("arm", "cancel"):
            self.create_service(Trigger, f"/amr/line/continue/{act}",
                                lambda req, res, act=act: self._trigger(
                                    f"continue {act}", lambda: self.job.continue_on_start(act == "arm"), res))

        self.create_steady_timer(self.dt, self._tick)
        self.create_timer(1.0, self._publish_state)
        self._publish_state()
        self.get_logger().info(
            f"line layer up, generation {self._generation}: "
            f"k_ratio={runtime.K_RATIO} kd={runtime.KD} "
            f"normal={vehicle_config.AUTO_RPM:g} rpm high={vehicle_config.AUTO_HIGH_RPM:g} rpm "
            f"rate floor={self.reader.min_hz} Hz "
            f"auto-resume clear={self.job.auto_resume_clear_s} s"
        )

    # -- tape localization (tracked plan 3, P1 shadow) -------------------------
    def _tape_runtime(self):
        """The teach/shadow runtime, or None when the site mission does not load (logged)."""
        from agv_core import mission  # noqa: PLC0415

        from amr_line import tape_locator, tape_runtime  # noqa: PLC0415

        p = self.get_parameter
        name = str(vehicle_config.TAPE_LOC_SITE_MISSION)
        try:
            site = mission.load_site(name)
        except mission.MissionError as e:
            self.get_logger().error(f"tape localization unavailable: {e}")
            return None
        status = str(p("loc_status").value)
        rev = int(p("loc_map_revision").value)
        g = int(p("loc_graph_revision").value)
        selection = None
        if not status and p("loc_map_id").value and rev >= 0:
            selection = {"map_id": str(p("loc_map_id").value), "map_revision": rev,
                         "graph_revision": g if g >= 0 else None}
        maps_dir = os.path.expanduser(str(p("maps_dir").value))
        rt = tape_runtime.TapeRuntime(
            site, tape_locator.Params.from_profile(vehicle_config), maps_dir=maps_dir,
            state_dir=os.path.expanduser(str(p("state_dir").value)), selection=selection,
            resolve_sha=lambda m, r: self._bundle_sha(maps_dir, m, r), status=status,
            shadow_circuit=str(vehicle_config.TAPE_LOC_SHADOW_CIRCUIT))
        self.get_logger().info(f"tape localization: {rt.detail}")
        return rt

    def _site_live(self):
        """tape_loc.live: the site mission is the job; trips stop, branch and turn by position."""
        if not bool(vehicle_config.TAPE_LOC_LIVE):
            return
        rt = self.tapeloc
        if rt is None or rt.graph is None:
            why = "the site mission did not load" if rt is None else rt.detail
            self.get_logger().error(f"tape_loc.live but no trips: {why}")
            return
        from amr_line import tape_locator  # noqa: PLC0415

        self.job.configure_site(tape_locator.Params.from_profile(vehicle_config), rt.compile_trip)
        ok, msg = self.job.set_mission(rt.m)
        self.get_logger().info(f"position engine live: {msg}" if ok else f"position engine: {msg}")

    def _srv_trip(self, req, res):
        action, arg = req.action.strip(), (req.arg or "").strip()
        if action == "call":
            res.ok, res.message = self.job.trip_call(arg, self._ros_now())
        elif action == "cancel":
            res.ok, res.message = self.job.trip_cancel(arg)
        elif action == "confirm_released":
            res.ok, res.message = self.job.confirm_released()
        elif action == "confirm_off":
            res.ok, res.message = self.job.confirm_off()
        elif action == "status":
            st = self.job.trip_status()
            res.ok = self.job.site is not None
            res.message = ("; ".join(f"{k[5:]}: {v}" for k, v in st.items() if v) or "no trip, no calls") \
                if res.ok else "no site mission is the job (tape_loc.live false, or another mission selected)"
        else:
            res.ok, res.message = False, f"unknown trip action {action!r}: call, cancel, confirm_released, " \
                                         f"confirm_off, status"
        if action != "status":
            self.get_logger().info(f"trip {action} {arg}: {res.message}")
            self._event("LINE_MISSION", f"trip {action} {arg}: {res.message}".replace("  ", " "),
                        Event.INFO if res.ok else Event.WARN)
            self._publish_state()
        return res

    # -- station calling (manuals/station-call-plan.md P3): nothing below exists when it is off ---
    def _station_setup(self):
        self._trolley = None            # the latest TrolleyState
        self._trolley_t: float | None = None
        self._order_pub = None
        self._order_published = None
        self._order_driving = False
        if not vehicle_config.STATION_ENABLED:
            return
        # Lazy, so a stale amr_interfaces build cannot hurt a switched-off vehicle.
        from amr_interfaces.msg import OrderState, TrolleyState  # noqa: PLC0415

        self._OrderState, self._TrolleyState = OrderState, TrolleyState
        self.create_subscription(TrolleyState, "/amr/rear/trolley", self._on_trolley, RELIABLE_1)
        self._order_pub = self.create_publisher(OrderState, "/amr/line/order_state", LATCHED)
        self.create_service(LineTeach, "/amr/line/order", self._srv_order)
        self.create_timer(1.0, lambda: self._publish_order(force=True))
        self.get_logger().warning("station calling is ON: an accepted order leaves HOME with no Start")
        if vehicle_config.STATION_NO_TROLLEY_RUN:
            self.get_logger().warning(
                "station.no_trolley_run is ON: unknown trolley and rear field states do not block a "
                "departure or a pivot, and no stop needs a trolley. A station call leaves HOME with "
                "no rear check. No trolleys on this vehicle.")

    def _on_trolley(self, m) -> None:
        self._trolley, self._trolley_t = m, time.monotonic()

    def _rear(self, now: float):
        """(trolley, rear_clear) as Inputs want them. Stale means unknown: the same freshness as the
        front field, so a dead trolley_node reads unknown within it."""
        m = self._trolley
        if m is None or self._trolley_t is None or now - self._trolley_t > self.field_fresh:
            return "unknown", None
        T = self._TrolleyState
        trolley = {T.ABSENT: "absent", T.PRESENT: "present"}.get(m.state, "unknown")
        return trolley, {T.FIELD_CLEAR: True, T.FIELD_VIOLATED: False}.get(m.rear_field)

    def _srv_order(self, req, res):
        """The bridge's one action. The reply says only "taken": the result is in OrderState."""
        action, parts = req.action.strip(), (req.arg or "").split()
        if action == "depart" and len(parts) == 2:
            res.ok, res.message = self.job.order_request(parts[0], parts[1])
        elif action == "cancel" and len(parts) == 2:
            res.ok, res.message = self.job.order_cancel(parts[0], parts[1])
        else:
            res.ok, res.message = False, "order: depart <orderId> <machine> | cancel <orderId> <actionId>"
        self.get_logger().info(f"order {action} {req.arg}: {res.message}")
        return res

    def _publish_order(self, force=False) -> None:
        if self._order_pub is None:
            return
        snap = self.job.order_snapshot()
        T = self._TrolleyState
        trolley, rear = self._rear(time.monotonic())
        body = {**snap, "driving": self._order_driving,
                "trolley": {"absent": T.ABSENT, "present": T.PRESENT}.get(trolley, T.UNKNOWN),
                "rear_field": {True: T.FIELD_CLEAR, False: T.FIELD_VIOLATED}.get(rear, T.FIELD_UNKNOWN)}
        if not force and body == self._order_published:
            return
        self._order_published = body
        m = self._OrderState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.generation = self._generation
        for k, v in body.items():
            if hasattr(m, k):   # mw2/me2_status: an OrderState built before 2026-11-11 has neither
                setattr(m, k, v)
        self._order_pub.publish(m)

    @staticmethod
    def _bundle_sha(maps_dir, map_id, revision):
        from amr_mission import map_bundle as mb  # noqa: PLC0415

        return mb.manifest_sha(maps_dir, map_id, revision)

    def _ros_now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_amcl(self, m: PoseWithCovarianceStamped) -> None:
        if self.tapeloc is None:
            return
        q = m.pose.pose.orientation
        yaw = 2.0 * math.atan2(q.z, q.w)
        self._amcl_pose = (m.pose.pose.position.x, m.pose.pose.position.y, yaw)
        self._amcl_pose_t = time.monotonic()
        c = m.pose.covariance
        verdict = self.tapeloc.amcl(self._ros_now(), m.header.stamp.sec + m.header.stamp.nanosec * 1e-9,
                                    m.pose.pose.position.x, m.pose.pose.position.y, yaw, c[0], c[1], c[7])
        self._trip_log_safe(self._trip_log_amcl, m, yaw, c, verdict)

    def _on_readiness(self, m: LocalizationState) -> None:
        if self.tapeloc is not None and int(m.generation) == self._generation:
            self._monitor, self._monitor_t = m, time.monotonic()
            self.tapeloc.readiness(self._ros_now(), int(m.state), str(m.reason))
            self._trip_log_safe(self._trip_log_ready, m)

    def _travel(self, now: float):
        """Signed forward wheel travel, m (vehicle terms, as diff_drive_odom), or None."""
        w = self._wheels
        if w is None or self._wheels_t is None or now - self._wheels_t > self.wheels_fresh:
            return None
        if not (w.left_valid and w.right_valid):
            return None
        return 0.5 * vehicle_config.WHEEL_DIA_M / 2.0 * (w.left_pos_rad + w.right_pos_rad)

    def _tapeloc_tick(self, now: float) -> None:
        rt = self.tapeloc
        if rt is None:
            return
        _counts, _per_rev, still = self._wheel_inputs(now)
        u = self.job.tape.uturn_snapshot() or {}
        phase = (u.get("phase") or "") if u.get("active") else ""
        # A kink pivot or the U-turn spin sweeps the sensor across the tape: #LCP 0 holds the
        # fork detectors as they were (no phantom junction in a teach pass or the shadow
        # locator), and the recorder notes the pivot to drop the corner's own fork episode.
        pivot = self.job.pivoting or phase in ("stopping", "spin", "center", "settle")
        nlcp = 0 if pivot else (self.reader.sensor() or {}).get("nlcp")
        rt.tick(self._ros_now(), self._travel(now), nlcp, still, phase, pivot)
        self.tape_health.where(rt.snapshot() if rt.loc is not None else None)
        events = rt.drain_events()
        for level, text in events:
            self._event("LINE_LOC", text, Event.WARN if level == "warn" else Event.INFO)
        if events:
            self._publish_state()

    def _srv_teach(self, req, res):
        if self.tapeloc is None:
            res.ok, res.message = False, "tape localization unavailable (site mission refused: see the log)"
        else:
            res.ok, res.message = self.tapeloc.teach(self._ros_now(), req.action.strip(), req.arg)
        self.get_logger().info(f"teach {req.action} {req.arg}: {res.message}")
        self._event("LINE_LOC", f"teach {req.action}: {res.message}", Event.INFO if res.ok else Event.WARN)
        self._publish_state()
        return res

    def _srv_at_home(self, req, res):
        res.success, res.message = self._at_home("")
        return res

    def _at_home(self, how):
        """At home, from the web (how "") or the panel (how: the combination). (ok, message)."""
        if self.tapeloc is None:
            return False, "tape localization unavailable"
        if self.job.calling and not self._manual_on_fresh_panel():
            # Automatic departure relies on this press (plan O11): a person looking at the vehicle.
            msg = "At home needs the selector in MANUAL with station calling on"
            self._event("LINE_LOC", msg, Event.WARN)
            return False, msg
        now = time.monotonic()
        counts, _per_rev, still = self._wheel_inputs(now)
        why = ""
        if not self.job.idle_for_position():
            # It would wipe the locator of a held trip.
            why = f"At home refused: the job is {lj.STATE_NAMES[self.job.state]}" + (
                ", with a trip" if self.job.trip is not None else "")
        elif counts is not None and not still:
            why = "At home refused: the wheels are moving"
        if why:
            why += f" ({how})" if how else ""
            self._event("LINE_LOC", why, Event.WARN)
            return False, why
        ok, msg, pose = self.tapeloc.at_home(fresh_ready=True) if self.job.calling else self.tapeloc.at_home()
        if ok:
            self.job.at_home_pressed()
            self._publish_seed(pose)
            self._position.press(now, counts)
        msg += f" ({how})" if how else ""
        self._event("LINE_LOC", msg, Event.INFO if ok else Event.WARN)
        self._publish_state()
        return ok, msg

    def _publish_seed(self, pose) -> None:
        """The taught HOME on /initialpose: the monitor starts checking again."""
        m = PoseWithCovarianceStamped()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = "map"
        m.pose.pose.position.x, m.pose.pose.position.y = float(pose[0]), float(pose[1])
        m.pose.pose.orientation.z = math.sin(pose[2] / 2.0)
        m.pose.pose.orientation.w = math.cos(pose[2] / 2.0)
        from amr_line.tape_locator import initial_pose_cov  # noqa: PLC0415 - as the locator itself

        m.pose.covariance = initial_pose_cov()
        self._pub_initialpose.publish(m)

    def _position_tick(self, i, now: float) -> None:
        """Automatic confirm at HOME (amr_line.position_confirm). No motion: it can only seed AMCL and
        call the monitor's confirm, which checks again."""
        if self.tapeloc is None:
            return
        m = self._monitor
        act = self._position.tick(position_confirm.Facts(
            now=now,
            monitor_state=None if m is None else int(m.state),
            monitor_t=self._monitor_t,
            can_confirm=bool(m is not None and m.can_confirm),
            scan_match=-1.0 if m is None else float(m.scan_match),
            scan_long=-1.0 if m is None else float(m.scan_long),
            job_idle=self.job.idle_for_position(),
            reset_edge=bool(i.reset_edge),
            tape_seen=bool((i.sensor or {}).get("has_track")),
            pose=self._amcl_pose,
            pose_t=self._amcl_pose_t,
            home=self.tapeloc.home_pose(),
            counts=i.counts,
            counts_per_rev=i.counts_per_rev,
            parked_at_home=self.job.parked_at_home(i),
            wheels_still=bool(i.wheels_still),
        ))
        if act == position_confirm.SEED:
            home = self.tapeloc.home_pose()
            if home is not None:
                self._publish_seed(home)
        elif act == position_confirm.CONFIRM:
            self._call_confirm(now)
        for level, text in self._position.events:
            self._event("LINE_LOC", text, Event.WARN if level == "warn" else Event.INFO)
        self._position.events.clear()

    def _call_confirm(self, now: float) -> None:
        if not self._confirm_client.service_is_ready():
            self._position.reply(now, False, "the confirm service is not up")
            return

        def done(future):
            t = time.monotonic()
            try:
                r = future.result()
            except Exception as e:  # noqa: BLE001 - any failure of the call is a failed confirm
                self._position.reply(t, False, str(e))
            else:
                self._position.reply(t, bool(r.success), str(r.message))

        self._confirm_client.call_async(Trigger.Request()).add_done_callback(done)

    def _manual_on_fresh_panel(self) -> bool:
        p, t = self._panel, self._panel_t
        return p is not None and t is not None and time.monotonic() - t <= self.panel_fresh \
            and bool(p.valid) and not bool(p.mode_auto)

    # -- intake ------------------------------------------------------------
    def _on_track(self, m: LineTrack) -> None:
        self.reader.update(m, time.monotonic())
        self.tape_health.track(m.track_level, m.nlcp, m.event_flag, m.source)

    def _on_panel(self, m: PanelState) -> None:
        now = time.monotonic()
        self._panel, self._panel_t = m, now
        if m.start_edge:
            self._start_edge_t = now  # consumed by exactly one tick
        if m.reset_edge:
            self._reset_edge = True
        # At home from the panel (amr_line.home_combo): Start + Reset held 1 s under MANUAL. Older
        # amr_interfaces without the levels: never.
        start_held, reset_held = bool(getattr(m, "start_held", False)), bool(getattr(m, "reset_held", False))
        if self._home_combo.tick(now, bool(m.valid), bool(m.mode_auto), start_held, reset_held,
                                 bool(m.start_edge), bool(m.reset_edge)):
            self._at_home(f"panel: Start + Reset held {home_combo.HOLD_S:g} s")

    def _on_lease(self, m: ControlLease) -> None:
        # Replayed or reordered leases never move authority backwards.
        gen, seq = int(m.generation), int(m.seq)
        if gating.lease_stale(self._lease, m.instance, gen, seq, monotonic_generation=True):
            return
        self._lease, self._lease_t = m, time.monotonic()

    def _on_rfid(self, m: StationDetection) -> None:
        self.rfid_in.on_message(time.monotonic(), bool(m.heartbeat), str(m.rfid_tag), m.encounter_seq,
                                m.generation, bool(m.comms_ok), float(m.tag_age_s),
                                bool(getattr(m, "work_mode_mismatch", False)))

    def _on_marker(self, m: MarkerEvent) -> None:
        gen = int(m.generation)
        st = self._marker_status
        if gen != st["generation"]:
            # drive_node restarted its marker stream: what came before is not continuous.
            self._marker_events.clear()
            st["generation"] = gen
            st["base"] = int(m.seq) if m.heartbeat else max(0, int(m.seq) - 1)
        if not m.heartbeat and m.code:
            self._marker_events.append((int(m.seq), int(m.code), int(m.direction), int(m.lcp2_mm),
                                        bool(m.line_good)))
        st["ok"], st["status"] = bool(m.markers_ok), str(m.status)
        self._marker_t = time.monotonic()

    def _markers(self, now: float) -> dict:
        """The marker snapshot. A silent stream (no heartbeat for 2.5 s) is not ok."""
        fresh = self._marker_t is not None and now - self._marker_t <= 2.5
        st = dict(self._marker_status)
        if not fresh:
            st["ok"], st["status"] = False, "no marker data"
        st["encounters"] = list(self._marker_events)
        return st

    def _rfid(self, now: float) -> dict:
        """agv_core.drivers.rfid snapshot shape. A silent node is a link that is down."""
        return self.rfid_in.snapshot(now)

    def _on_wheels(self, m: WheelStates) -> None:
        self._wheels, self._wheels_t = m, time.monotonic()

    def _on_imu(self, m: Imu) -> None:
        self._imu_wz, self._imu_t = float(m.angular_velocity.z), time.monotonic()

    def _on_odom(self, m: Odometry) -> None:
        self._odom = (float(m.twist.twist.linear.x), float(m.twist.twist.angular.z))
        self._odom_t = time.monotonic()

    def _on_mux(self, m: MuxState) -> None:
        self._mux_scale, self._mux_t = float(m.speed_scale), time.monotonic()

    def _motion_inputs(self, now: float):
        """(yaw_rate, v_meas, warning_scale). Gyro first, odometry as the fallback;
        None when neither is fresh, which takes HIGH away. A stale mux reads as no
        warning: the U-turn budget then runs, which faults rather than waits."""
        odom_ok = self._odom_t is not None and now - self._odom_t <= self.odom_fresh
        imu_ok = self._imu_t is not None and now - self._imu_t <= self.imu_fresh
        v = self._odom[0] if odom_ok else None
        yaw = self._imu_wz if imu_ok else (self._odom[1] if odom_ok else None)
        mux_ok = self._mux_t is not None and now - self._mux_t <= self.mux_fresh
        return yaw, v, (self._mux_scale if mux_ok else 1.0)

    def _wheel_inputs(self, now: float):
        """(counts, counts_per_rev, still) from a FRESH /wheel_states, else nothing."""
        w = self._wheels
        if w is None or self._wheels_t is None or now - self._wheels_t > self.wheels_fresh:
            return None, 0.0, False
        still = drive_state.still(w.left_vel_rad_s, w.right_vel_rad_s, self.still_w,
                                  valid=w.left_valid and w.right_valid)
        counts = (int(w.left_counts), int(w.right_counts)) if w.counts_valid else None
        return counts, float(w.counts_per_wheel_rev), bool(still)

    def _on_mode(self, m: ModeState) -> None:
        self._mode = m

    def _drives_fresh(self, now: float) -> bool:
        return self._drives_t is not None and now - self._drives_t <= self.drives_fresh_s

    def _on_drives(self, m: DriveStatus) -> None:
        self._torque_off_msg = drive_state.torque_off(m.operational, m.left_state, m.right_state)
        self._drive_link, self._drives_operational = str(m.link_state), bool(m.operational)
        self._drives_t = time.monotonic()

    def _on_output_paths(self, m) -> None:
        clear = drive_state.field_clear(getattr(m, "status", None), self.field_index)
        if clear is None:
            return  # a malformed array is no evidence at all: the old one ages out
        self._field_clear = clear
        self._field_t = time.monotonic()

    def _field(self, now: float) -> bool | None:
        """clear / violated / None (unknown: no sample, or the stream stalled)."""
        if self.field_source == "assume_clear":
            return True
        if self._field_t is None or now - self._field_t > self.field_fresh:
            return None
        return self._field_clear

    # -- authority ---------------------------------------------------------
    def _authority(self, now: float):
        if self._lease is None or self._lease_t is None or now - self._lease_t > self.lease_fresh:
            return None, 0
        return (str(self._lease.instance), int(self._lease.generation)), int(self._lease.allowed)

    def _inputs(self, now: float, dt: float) -> lj.Inputs:
        authority, allowed = self._authority(now)
        panel_ok = (
            self._panel is not None
            and self._panel_t is not None
            and now - self._panel_t <= self.panel_fresh
        )
        start_edge_t, self._start_edge_t = self._start_edge_t, None
        reset_edge, self._reset_edge = self._reset_edge, False
        track_ok, track_cause = self.reader.usable(now)
        counts, per_rev, still = self._wheel_inputs(now)
        yaw, v_meas, scale = self._motion_inputs(now)
        rear = self._rear(now) if self.job.calling else ("unknown", None)
        return lj.Inputs(
            now=now,
            dt=dt,
            sensor=self.reader.sensor(),
            sensor_age_s=self.reader.age_s(now),  # None = never decoded: a silent sensor (WP-A3)
            track_ok=track_ok,
            track_cause=track_cause,
            panel_valid=bool(panel_ok and self._panel.valid),
            panel_auto=bool(panel_ok and self._panel.mode_auto),
            panel_link_lost=bool(panel_ok and not self._panel.valid),
            start_edge=start_edge_t is not None,
            start_edge_t=start_edge_t,
            reset_edge=reset_edge,
            lease_allowed=allowed,
            lease_line=ControlLease.LINE,
            authority=authority,
            torque_off=bool(
                self._torque_off_msg
                and self._drives_t is not None
                and now - self._drives_t <= self.drives_fresh_s
            ),
            field_clear=self._field(now),
            drives_fresh=bool(
                self._drives_t is not None and now - self._drives_t <= self.drives_fresh_s
            ),
            # A stale report says nothing about the link: "" and None are "unknown".
            drive_link=self._drive_link if self._drives_fresh(now) else "",
            drives_operational=self._drives_operational if self._drives_fresh(now) else None,
            rfid=self._rfid(now),
            markers=self._markers(now),
            counts=counts,
            counts_per_rev=per_rev,
            wheels_still=still,
            yaw_rate=yaw,
            v_meas=v_meas,
            warning_scale=scale,
            loc=self.tapeloc.loc_state() if getattr(self, "tapeloc", None) is not None else None,
            trolley=rear[0],
            rear_clear=rear[1],
            loc_ready=bool(getattr(self, "tapeloc", None) is not None and self.tapeloc.ready),
        )

    # -- services ----------------------------------------------------------
    def _srv_clear(self, req, res):
        if self.job.calling and self.job.state == lj.FAULT:
            res.success, res.message = False, "press Reset on the panel"
            return res
        if self.job.clear():
            # Do not leave the last nonzero command live until the mux's
            # freshness timeout: zero it now.
            self._publish_cmd(0.0, 0.0)
        res.success, res.message = True, "cleared"
        self.get_logger().info("clear: the run is cleared")
        self._publish_state()
        return res

    def _trigger(self, label, call, res):
        """One engineer Trigger (branch order, speed toggle, forced U-turn, continue): the job's
        (ok, message) as the reply, logged under `label`, the state published at once."""
        res.success, res.message = call()
        self.get_logger().info(f"{label}: {res.message}")
        self._publish_state()
        return res

    def _plain_mission(self):
        """missions/empty.json (the site's U-turn tags), or None - no tags at all -
        when it is missing or refused, so a bad file never blocks line following."""
        from agv_core import mission  # noqa: PLC0415

        try:
            return mission.load("empty")
        except mission.MissionError as e:
            self.get_logger().error(f"plain line following without U-turn tags: {e}")
            return None

    def _srv_mission(self, req, res):
        from agv_core import mission  # noqa: PLC0415

        name = (req.name or "").strip()
        rt = self.tapeloc
        if rt is not None and name == rt.m["MISSION_NAME"]:
            res.ok, res.message = self.job.set_mission(rt.m)
            self.get_logger().info(f"mission: {res.message}")
            self._publish_state()
            return res
        try:
            doc = self._plain_mission() if name in ("", "none") else mission.load(name)
        except mission.MissionError as e:
            res.ok, res.message = False, f"mission {name!r} refused: {e}"
        else:
            res.ok, res.message = self.job.set_mission(doc, (req.destination or "").strip())
        self.get_logger().info(f"mission: {res.message}")
        self._publish_state()
        return res

    # -- the tick ----------------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._t_last = now - self._t_last, now
        before = self.job.state

        self._tl_inputs = self._inputs(now, min(dt, 5 * self.dt))
        left, right = self.job.tick(self._tl_inputs)
        if self.job.trip_new is not None:
            # A trip's Start: the locator moves onto its route before the pre-move warning ends.
            route, self.job.trip_new = self.job.trip_new, None
            self._tl_route = route
            ok, msg = self.tapeloc.begin_trip(route) if self.tapeloc is not None else (False, "no locator")
            if not ok:
                self._event("LINE_LOC", f"{msg}: the trip will hold (position)", Event.WARN)
        self._tapeloc_tick(now)
        kept = getattr(self.job.tape, "forks_kept", None)
        while kept:
            # The MLS kept the ordered tape at this fork: AMCL may not call it the wrong one.
            msg = self.tapeloc.confirm_fork(kept.pop(0)) if self.tapeloc is not None else ""
            if msg:
                self._event("LINE_LOC", msg, Event.WARN)
        self._position_tick(self._tl_inputs, now)
        engine_events = self.job.tape.drain_events()
        for level, text in engine_events:
            self._event("LINE_MISSION", text, Event.WARN if level == "warn" else Event.INFO)
        marker_events = self.job.drain_marker_events()
        for level, text in marker_events:
            self._event("LINE_MARKER", text, Event.WARN if level == "warn" else Event.INFO)
        if engine_events or marker_events:
            self._publish_state()
        self._flight_tick(now, before, left, right, engine_events + marker_events)
        self._trip_log_tick(now, before, left, right)
        if self.job.refused:
            self._event("LINE_MISSION", f"Start refused: {self.job.refused}", Event.WARN)
            self.job.refused = None
            self._publish_state()
        if self.job.calling:
            for code, text in self.job.drain_station_events():
                self._event(code, text)
            self._order_driving = self.job.state == lj.RUNNING and (left != 0.0 or right != 0.0)
            self._publish_order()

        if self.job.state == lj.RUNNING:
            v, omega = kinematics.wheels_to_body(left, right)
            self._publish_cmd(v, omega)
        elif before == lj.RUNNING:
            # Explicit zero on the falling edge, for the same reason as above.
            self._publish_cmd(0.0, 0.0)

        if self.job.state != before:
            self.get_logger().info(
                f"line {lj.STATE_NAMES[before]} -> {lj.STATE_NAMES[self.job.state]}"
                f" {self.job.reason}"
            )
            if before in (lj.RUNNING, lj.HOLD) and self.job.state in (lj.DONE, lj.FAULT, lj.IDLE):
                self._write_tape_health(lj.STATE_NAMES[self.job.state])
            self._publish_state()
        elif self.job.wants_power() != self._power_published:
            self._publish_state()  # a hold changing cause can change drive_power: say so now

    def _flight_tick(self, now, before, left, right, events) -> None:
        sensor = self.reader.sensor() or {}
        d = self.job.diag or {}
        u = self.job.tape.uturn_snapshot() or {}
        state = self.job.state
        self.flight.add(
            t=f"{now:.3f}", job=lj.STATE_NAMES[state], engine=d.get("state", ""),
            nlcp=sensor.get("nlcp"), level=sensor.get("track_level"),
            tracks_mm=" ".join(str(t.get("pos_mm")) for t in sensor.get("tracks") or ()),
            has_track=d.get("has_track"), e_used_mm=d.get("e_used"),
            v_base_rpm=f"{d.get('v_base', 0.0):.0f}", left_rpm=f"{left:.0f}", right_rpm=f"{right:.0f}",
            kink=(self.job.kink or {}).get("direction", "") or (
                f"roll-{self.job.corner.direction}" if self.job.corner.active else ""),
            uturn=(u.get("phase") or "") if u.get("active") else "",
            travel_m=f"{self.job.followed_m:.3f}", S_m=getattr(self.job.tape, "S", None),
            sigma_m=(self.job.tape.loc or {}).get("sigma") if hasattr(self.job.tape, "loc") else None,
            intent=self.job.tape.branch.ladder.intent(), note="; ".join(x for _l, x in events)[:200])
        why = None
        if state != before and state in (lj.DONE, lj.FAULT, lj.HOLD) and before in (lj.RUNNING, lj.HOLD):
            why = f"{lj.STATE_NAMES[state]} {self.job.reason}"
        elif self.job.kinks != self._fr_kinks:
            why = "kink"
        elif self.job.corners != self._fr_corners:
            why = "corner"
        elif self.job.tape.uturn_last is not self._fr_uturn_done and self.job.tape.uturn_last:
            why = "uturn done"
        forks = getattr(self.job.tape, "fork_log", ())
        if not why and len(forks) > self._fr_forks:
            why = f"fork {forks[-1]['id']} {forks[-1]['verdict']}"
        self._fr_forks = len(forks)
        self._fr_kinks = self.job.kinks
        self._fr_corners = self.job.corners
        self._fr_uturn_done = self.job.tape.uturn_last
        if why:
            try:
                path = self.flight.dump(why)
            except OSError as e:
                self.get_logger().warn(f"line trace not written: {e}")
                return
            self.get_logger().info(f"line trace: {path}")

    def _trip_log_safe(self, fn, *args) -> None:
        """Logging must never be what stops a vehicle: any problem is reported once, and the tick
        or callback goes on."""
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            if not self._tl_failed:
                self._tl_failed = True
                self.get_logger().error(f"trip log: {e!r}; the run goes on without it")

    def _trip_log_amcl(self, m, yaw, c, verdict) -> None:
        if not self.triplog.active:
            return
        snap = self.tapeloc.loc.snapshot() if self.tapeloc.loc is not None else {}
        self.triplog.add("amcl", t=round(time.monotonic(), 3), x=round(m.pose.pose.position.x, 3),
                         y=round(m.pose.pose.position.y, 3), yaw=round(yaw, 4), cov_xx=c[0], cov_yy=c[7],
                         verdict=verdict or "", S=snap.get("S"), sigma=snap.get("sigma"),
                         leg=snap.get("leg"), lateral=snap.get("lateral"), innov=snap.get("innov"))

    def _trip_log_ready(self, m) -> None:
        now = time.monotonic()
        key = (int(m.state), str(m.reason))
        if self.triplog.active and (key != self._tl_ready or now - self._tl_ready_t >= 1.0):
            self._tl_ready, self._tl_ready_t = key, now
            self.triplog.add("ready", t=round(now, 3), state=int(m.state), reason=str(m.reason),
                             scan_match=round(float(m.scan_match), 3),
                             scan_long=round(float(m.scan_long), 3))

    def _trip_log_tick(self, now, before, left, right) -> None:
        self._trip_log_safe(self._trip_log_row, now, before, left, right)
        err = self.triplog.drain_error()
        if err:
            self.get_logger().warn(f"trip log not written: {err}")

    def _trip_log_row(self, now, before, left, right) -> None:
        job, log, state = self.job, self.triplog, self.job.state
        if state in (lj.ARMED, lj.RUNNING, lj.HOLD) and not log.active:
            self._trip_log_begin()
        if not log.active:
            return
        t = job.tape
        if self._tl_route is not None:
            r, self._tl_route = self._tl_route, None
            log.add("route", ident=r.ident, stops=r.stops, nodes=r.nodes, events=r.events, zones=r.zones,
                    uturn=r.uturn)
        for f in self._tl_forks.new(t):
            log.add("fork", t=round(now, 3), **f)
        # Standing still in a hold for minutes needs no 50 Hz. RUNNING always gets every tick.
        self._tl_tick += 1
        if state == before == lj.HOLD and left == 0.0 and right == 0.0 and self._tl_tick % 10:
            return
        sensor = self.reader.sensor() or {}
        d = job.diag or {}
        i = self._tl_inputs
        u = t.uturn_snapshot() or {}
        loc = self.tapeloc.loc.snapshot() if self.tapeloc is not None and self.tapeloc.loc is not None else {}
        w = self._wheels
        log.add("tick", t=round(now, 3), job=lj.STATE_NAMES[state], reason=job.reason, hold=job.hold_cause,
                engine=d.get("state", ""), nlcp=sensor.get("nlcp"),
                tracks=[x.get("pos_mm") for x in sensor.get("tracks") or ()],
                level=sensor.get("track_level"),
                has_track=d.get("has_track"), e_used=d.get("e_used"), followed=job.f.followed_mm,
                v_base=d.get("v_base"), left=round(left, 1), right=round(right, 1),
                wl=None if w is None else round(w.left_vel_rad_s, 3),
                wr=None if w is None else round(w.right_vel_rad_s, 3),
                kink=(job.kink or {}).get("direction", ""),
                uturn=(u.get("phase") or "") if u.get("active") else "",
                travel=round(job.followed_m, 3), S=loc.get("S"), sigma=loc.get("sigma"), leg=loc.get("leg"),
                health=loc.get("health"), amcl_out=loc.get("amcl_out"), lateral=loc.get("lateral"),
                rejected=loc.get("rejected"), last_reject=loc.get("last_reject"),
                intent=t.branch.ladder.intent(), armed=(getattr(t, "_armed", None) or {}).get("id"),
                unhonoured=t.branch.unhonoured, next=t.next_event() if hasattr(t, "next_event") else "",
                high=bool(t.high), high_why=getattr(t, "high_why", ""),
                tier=getattr(t, "speed_tier", "high" if t.high else "normal"),
                zone=t._zone_at(t.S) if hasattr(t, "_zone_at") else None,
                field_clear=None if i is None else i.field_clear, auto=None if i is None else i.panel_auto,
                link=None if i is None else i.drive_link,
                torque_off=None if i is None else i.torque_off,
                panel_valid=None if i is None else i.panel_valid)
        if state in (lj.DONE, lj.FAULT, lj.IDLE):
            log.end(f"{lj.STATE_NAMES[state]} {job.reason}")

    def _trip_log_begin(self) -> None:
        job, rt = self.job, self.tapeloc
        trip = getattr(job, "trip", None)
        label = trip.describe() if trip is not None else (job.mission or {}).get("MISSION_NAME", "line run")
        p = rt.p if rt is not None else None
        self.triplog.begin(label, graph=rt.graph_name if rt is not None else "",
                           map=(rt.sel or {}).get("map_id", "") if rt is not None else "",
                           profile=os.environ.get("AGV_PROFILE", ""), generation=self._generation,
                           cruise=getattr(job.tape, "cruise", None), calling=bool(job.calling),
                           params=vars(p).copy() if p is not None and hasattr(p, "__dict__") else {})
        self._tl_forks.skip(job.tape)
        self._tl_tick, self._tl_ready = 0, None

    def _write_tape_health(self, result: str) -> None:
        """End of a run: append its tape-health bins (M3). A disk problem is logged, never raised."""
        bins = self.tape_health.drain()
        try:
            meta = {"generation": self._generation, "result": result}
            path = tape_health.write_run(self._state_dir, bins, meta)
        except OSError as e:
            self.get_logger().warn(f"tape health not written: {e}")
            return
        if path:
            self.get_logger().info(f"tape health: {len(bins)} bins -> {path}")

    # -- output ------------------------------------------------------------
    def _publish_cmd(self, v: float, omega: float) -> None:
        if v == 0.0 and omega == 0.0 and self._published_zero:
            return
        m = Twist()
        m.linear.x = float(v)
        m.angular.z = float(omega)
        self._pub_cmd.publish(m)
        self._published_zero = v == 0.0 and omega == 0.0

    def _publish_state(self) -> None:
        d = getattr(self.job, "diag", {}) or {}
        m = LineState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.generation = self._generation
        m.state = self.job.state
        m.hold_cause = self.job.hold_cause
        m.auto_resume = self.job.auto_resume()
        m.drive_power = bool(self.job.wants_power())
        self._power_published = m.drive_power
        m.engine_state = str(d.get("state", "idle"))
        m.has_track = bool(d.get("has_track", False))
        m.error_mm = float(d.get("e_mm") or 0.0)
        v, omega = (0.0, 0.0)
        if self.job.state == lj.RUNNING and d:
            v, omega = kinematics.wheels_to_body(d.get("n_l", 0.0), d.get("n_r", 0.0))
        m.v_mps, m.omega_rad_s = float(v), float(omega)
        m.followed_m = float(self.job.followed_m)
        m.track_hz = float(self.reader.hz() or 0.0)
        age = self.reader.age_s(time.monotonic())
        m.sample_age_s = -1.0 if age is None else float(age)  # -1 = never decoded
        m.track_source = "" if self.reader.last is None else str(self.reader.last.source)
        m.message = self.job.reason
        m.code = self._code()
        extra = {"hold_device": hold_policy.hold_device(self.job.hold_cause)}
        if self._position.detail:
            extra["home_detail"] = self._position.detail
        for k, v in {**self.job.mission_snapshot(), **extra}.items():
            if not hasattr(m, k):
                # Python updated by a restart, amr_interfaces not rebuilt: say so once and
                # keep publishing, rather than lose the line layer to an AttributeError.
                if k not in self._missing_fields:
                    self._missing_fields.add(k)
                    self.get_logger().warning(f"LineState has no field {k!r}: rebuild amr_interfaces")
                continue
            setattr(m, k, v)
        for k, v in self.job.marker_snapshot().items():
            setattr(m, k, v)
        if getattr(self, "tapeloc", None) is not None:
            for k, v in self.tapeloc.snapshot().items():
                setattr(m, k, v)
        self._pub_state.publish(m)
        if self.job.state != self._event_state:
            self._event_state = self.job.state
            self._event(m.code, m.message)

    def _code(self) -> str:
        """Alarm catalogue code for the current hold or fault; "" while it is driving."""
        if self.job.state in (lj.HOLD, lj.FAULT):
            if self.job.hold_cause:
                return alarms.hold_code(self.job.hold_cause)
            return "EXEC_PREREQ_LOST" if self.job.state == lj.FAULT else "WAITING_FOR_PREREQ"
        return ""

    def _event(self, code: str, detail: str, level: int | None = None) -> None:
        code = code or "MODE_CHANGE"
        level = alarms.level(code) if level is None else level
        text = f"line {lj.STATE_NAMES[self.job.state]}: {detail}"
        self._pub_event.publish(self.build_event("line_follow", level, code, text))
        self.triplog.add("event", t=round(time.monotonic(), 3), code=code,
                         level={Event.WARN: "warn", Event.ERROR: "error"}.get(level, "info"),
                         text=text)


def _stop(node) -> None:
    node.triplog.close()
    node.job.clear()
    node._publish_cmd(0.0, 0.0)


def main() -> None:
    run(LineFollowNode, before_destroy=_stop, catch_runtime=False)


if __name__ == "__main__":
    main()
