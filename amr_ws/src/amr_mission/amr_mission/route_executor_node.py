"""route_executor_node: runs a drawn route as FollowPath straights and Spin turns (spec §5, §7).

One action at a time. The permit lease names exactly the source that may move
the vehicle (FOLLOW during a straight, ROTATE during a turn, NONE otherwise),
the physical panel authorises every start and every resume, and every check
the spec lists is made here against the estimated pose, not trusted from an
action result alone:

  straight   cross-track from the drawn line (fault > limit), endpoint within
             tolerance AND wheels still 0.3 s before advancing, passing the
             endpoint outside tolerance is a fault, never a reverse;
  rotate     wheels still first; signed relative Spin; own unwrapped yaw from
             /odometry/filtered verifies direction and travel, centre drift is
             bounded, final map heading within tolerance; a paused turn resumes
             the REMAINING signed angle only;
  always     localisation READY, fresh sensors and panel, no /initialpose,
             no obstacle inside the active step's swept footprint (BLOCKED).
"""

from __future__ import annotations

import math
import os
import threading

import numpy as np
import rclpy
from action_msgs.msg import GoalStatus
from amr_navigation.compiler import ROTATE, STRAIGHT, CompiledStep, wrap
from amr_navigation.validate import load_keepout, validate
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_msgs.action import FollowPath, Spin
from nav_msgs.msg import Odometry, Path
from rclpy.action import ActionClient
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import LaserScan
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener

from amr_interfaces.msg import (
    ControlLease,
    LocalizationState,
    MotionPermit,
    PanelState,
    RunState,
    WheelStates,
)
from amr_interfaces.srv import RunMission
from amr_mission import map_bundle as mb
from amr_mission import run_fsm as fsm
from amr_navigation import footprint as fpmod
from amr_navigation import store

SENSOR_DATA = QoSProfile(
    depth=5, reliability=QoSReliabilityPolicy.BEST_EFFORT, durability=QoSDurabilityPolicy.VOLATILE
)
LATCHED = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL
)
RELIABLE_1 = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.VOLATILE
)

PHASE_INIT, PHASE_GOAL, PHASE_SETTLE = "init", "goal", "settle"


def _yaw(q) -> float:
    return math.atan2(2.0 * q.w * q.z, 1.0 - 2.0 * q.z * q.z)


def mission_matches_active_map(mission: dict, active: tuple[str, int, str]) -> str | None:
    """P4 (unified plan §5.6): a mission may only load onto the map AMCL is running.

    `active` is (id, revision, sha256) from the launch; ("", 0, "") means an
    unsupervised standalone stack, which binds to nothing (bench behaviour).
    Returns the refusal reason, or None when the mission's map IS the active map.
    """
    aid, arev, asha = active
    if not aid:
        return None
    m = mission.get("map", {})
    if m.get("id") != aid or int(m.get("revision", 0)) != arev:
        return f"mission is for map {m.get('id')} rev{m.get('revision')}, active map is {aid} rev{arev}"
    if asha and m.get("sha256") != asha:
        return "mission map hash differs from the active map bundle"
    return None


class RouteExecutor(Node):
    def __init__(self) -> None:
        super().__init__("route_executor")
        self.declare_parameter("maps_dir", os.path.expanduser("~/amr_maps"))
        self.declare_parameter("footprint_yaml", "")
        # Layer identity (unified plan U0/U4): stamped into every RunState and MotionPermit;
        # the active_map_* values are what a mission must match (U4 enforces).
        self.declare_parameter("generation", 0)
        self.declare_parameter("active_map_id", "")
        self.declare_parameter("active_map_revision", 0)
        self.declare_parameter("active_map_sha256", "")
        self.generation = int(self.get_parameter("generation").value)
        self.active_map = (
            str(self.get_parameter("active_map_id").value),
            int(self.get_parameter("active_map_revision").value),
            str(self.get_parameter("active_map_sha256").value),
        )
        self.declare_parameter("start_gate_m", 0.10)
        self.declare_parameter("start_gate_deg", 5.0)
        self.declare_parameter("settle_s", 0.3)
        self.declare_parameter("stationary_wheel_rad_s", 0.02)
        # Centre drift during a turn is measured on ODOMETRY (precise over one turn), not on
        # AMCL, whose estimate wanders several cm during a spin in place. Spec §5.3: 0.05 m.
        self.declare_parameter("centre_drift_m", 0.05)
        # The executor's own end-of-step verification against the AMCL pose. RPP's goal
        # checker already stops at 0.05 m / 2 deg (spec §5.2); this re-check must allow
        # the estimator's own noise (sim AMCL p95 ~0.06 m) or it fails good stops.
        # HARDWARE PLACEHOLDERS: sim AMCL wanders 1-3 deg during a spin in place, so a 2-3 deg
        # heading re-check trips on estimator noise, not on the turn (odometry travel is within 2 deg).
        self.declare_parameter("verify_position_m", 0.08)
        self.declare_parameter("verify_heading_deg", 5.0)
        self.declare_parameter("converge_m", 1.0)  # cross-track grace distance after a step starts
        self.declare_parameter("entry_correction_deg", 10.0)  # max entry-heading error folded into a turn
        self.declare_parameter("turn_travel_tolerance_deg", 2.0)
        self.declare_parameter("wrong_way_deg", 5.0)
        self.declare_parameter("wheels_age_limit_s", 0.10)
        self.declare_parameter("panel_age_limit_s", 0.20)
        self.declare_parameter("loc_age_limit_s", 1.5)
        self.declare_parameter("obstacle_points", 3)
        self.declare_parameter("stopping_horizon_m", 1.5)
        self.declare_parameter("clear_stable_s", 1.0)
        p = self.get_parameter
        self.maps_dir = os.path.expanduser(p("maps_dir").value)
        self.fp = fpmod.load(p("footprint_yaml").value or fpmod.default_path())
        self.start_gate_m, self.start_gate_rad = (
            p("start_gate_m").value,
            math.radians(p("start_gate_deg").value),
        )
        self.settle_s = p("settle_s").value
        self.w_eps = p("stationary_wheel_rad_s").value
        self.centre_drift_m = p("centre_drift_m").value
        self.verify_pos = p("verify_position_m").value
        self.verify_yaw = math.radians(p("verify_heading_deg").value)
        self.converge_m = p("converge_m").value
        self.entry_corr_max = math.radians(p("entry_correction_deg").value)
        self.turn_tol = math.radians(p("turn_travel_tolerance_deg").value)
        self.wrong_way = math.radians(p("wrong_way_deg").value)
        self.wheels_age, self.panel_age, self.loc_age = (
            p("wheels_age_limit_s").value,
            p("panel_age_limit_s").value,
            p("loc_age_limit_s").value,
        )
        self.obstacle_points = int(p("obstacle_points").value)
        self.horizon = p("stopping_horizon_m").value
        self.clear_stable_s = p("clear_stable_s").value

        self._lock = threading.RLock()
        self.fsm = fsm.RunFsm()
        self.compiled = None
        self.route = None
        self.manifest = None
        self.grid = None
        self.mission = None
        self.phase = PHASE_INIT
        self.goal_handle = None
        self.goal_result: str | None = None  # "succeeded" | "aborted" | "canceled"
        self.goal_run_id = ""
        self.we_cancelled = False
        self.settle_since: float | None = None
        self.turn_travelled = 0.0  # accumulated over pauses, signed
        self.turn_acc0: float | None = None
        self.turn_started_t: float | None = None
        self.turn_centre: tuple[float, float] | None = None  # odom xy where the turn ACTUALLY began
        self.turn_target: float | None = None  # signed angle to travel: drawn magnitude + entry correction
        self.turn_feedback = 0.0
        self.cross_track = 0.0
        self.clear_since: float | None = None
        self.last_initialpose_t: float | None = None
        self.paused_t: float | None = None
        self.odom_gap = False

        self._loc: LocalizationState | None = None
        self._loc_t = 0.0
        self._panel_t = 0.0
        self._panel: PanelState | None = None
        self._wheels_t = 0.0
        self._wheels_still = False
        self._odom_t = 0.0
        self._odom_yaw_prev: float | None = None
        self._odom_yaw_acc = 0.0
        self._odom_xy = (0.0, 0.0)
        self._scan: LaserScan | None = None
        self._last_state_key = None

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        io = ReentrantCallbackGroup()
        srv = MutuallyExclusiveCallbackGroup()
        self.create_subscription(
            LocalizationState, "/amr/localization_state", self._on_loc, LATCHED, callback_group=io
        )
        self.create_subscription(PanelState, "/amr/panel_state", self._on_panel, 10, callback_group=io)
        # The permit must carry the supervisor's instance (unified plan §4.3): the mux
        # refuses a permit from another instance/generation. Unsupervised: "" / 0.
        self._lease_instance = ""
        self._permit_seq = 0
        self.create_subscription(ControlLease, "/amr/control_lease", self._on_lease, 10, callback_group=io)
        self.create_subscription(
            WheelStates, "/wheel_states", self._on_wheels, SENSOR_DATA, callback_group=io
        )
        self.create_subscription(Odometry, "/odometry/filtered", self._on_odom, 10, callback_group=io)
        self.create_subscription(
            PoseWithCovarianceStamped, "/initialpose", self._on_initialpose, RELIABLE_1, callback_group=io
        )
        self.create_subscription(LaserScan, "/scan", self._on_scan, SENSOR_DATA, callback_group=io)
        self._follow = ActionClient(self, FollowPath, "/follow_path", callback_group=io)
        self._spin = ActionClient(self, Spin, "/spin", callback_group=io)
        self._permit_pub = self.create_publisher(MotionPermit, "/amr/motion_permit", RELIABLE_1)
        self._state_pub = self.create_publisher(RunState, "/amr/run_state", LATCHED)
        self.create_service(RunMission, "/amr/run_mission", self._srv_run, callback_group=srv)
        self.create_service(Trigger, "/amr/pause", self._srv_pause, callback_group=srv)
        self.create_service(Trigger, "/amr/abort", self._srv_abort, callback_group=srv)
        self.create_service(Trigger, "/amr/resume", self._srv_resume, callback_group=srv)
        self.create_service(Trigger, "/amr/ack_fault", self._srv_ack, callback_group=srv)
        self.create_timer(0.1, self._tick, callback_group=srv)
        self.create_timer(0.5, self._publish_state, callback_group=io)
        self.get_logger().info(f"IDLE; maps_dir {self.maps_dir}; footprint reach {self.fp.reach_m:.2f} m")

    # ---- inputs ------------------------------------------------------------------------

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_loc(self, m: LocalizationState) -> None:
        self._loc, self._loc_t = m, self._now()

    def _on_lease(self, m: ControlLease) -> None:
        if int(m.generation) == self.generation or self.generation == 0:
            self._lease_instance = m.instance

    def _on_panel(self, m: PanelState) -> None:
        self._panel, self._panel_t = m, self._now()
        if m.start_edge:
            with self._lock:
                self._start_edge()

    def _on_wheels(self, m: WheelStates) -> None:
        self._wheels_t = self._now()
        self._wheels_still = (
            m.left_valid
            and m.right_valid
            and abs(m.left_vel_rad_s) < self.w_eps
            and abs(m.right_vel_rad_s) < self.w_eps
        )

    def _on_odom(self, m: Odometry) -> None:
        t = self._now()
        yaw = _yaw(m.pose.pose.orientation)
        self._odom_xy = (m.pose.pose.position.x, m.pose.pose.position.y)
        if self._odom_yaw_prev is not None:
            if t - self._odom_t > 0.5:
                self.odom_gap = True  # continuity lost: a paused turn cannot resume on this
            self._odom_yaw_acc += wrap(yaw - self._odom_yaw_prev)
        self._odom_yaw_prev, self._odom_t = yaw, t

    def _on_initialpose(self, _m) -> None:
        self.last_initialpose_t = self._now()
        with self._lock:
            if self.fsm.state == fsm.EXECUTING:
                self._fault("initial pose injected during a step")
            elif self.fsm.state in (fsm.PAUSED, fsm.BLOCKED):
                self.fsm.invalidate_resume(
                    "initial pose changed; progress-based resume is invalid, abort the run"
                )
                self.odom_gap = True

    def _on_scan(self, m: LaserScan) -> None:
        self._scan = m

    def _pose(self) -> tuple[float, float, float] | None:
        try:
            t = self.tf_buffer.lookup_transform("map", "base_footprint", rclpy.time.Time())
        except Exception:  # noqa: BLE001
            return None
        return t.transform.translation.x, t.transform.translation.y, _yaw(t.transform.rotation)

    # ---- services -------------------------------------------------------------------------

    def _srv_run(self, req: RunMission.Request, res: RunMission.Response):
        with self._lock:
            try:
                mission = store.load_mission(self.maps_dir, req.mission_id)
                why = mission_matches_active_map(mission, self.active_map)
                if why:
                    raise store.StoreError(why)
                manifest, grid = mb.load(self.maps_dir, mission["map"]["id"], int(mission["map"]["revision"]))
                if manifest.sha256 != mission["map"]["sha256"]:
                    raise store.StoreError("map bundle hash differs from the mission manifest")
                route, sha = store.load_route(
                    self.maps_dir,
                    mission["map"]["id"],
                    mission["route"]["id"],
                    int(mission["route"]["revision"]),
                )
                if sha != mission["route"]["sha256"]:
                    raise store.StoreError("route file hash differs from the mission manifest")
                v = validate(
                    route,
                    manifest,
                    grid,
                    self.fp,
                    load_keepout(mb.revision_dir(self.maps_dir, manifest.map_id, manifest.revision)),
                )
                if not v.ok:
                    raise store.StoreError(
                        "route invalid on this map: "
                        + "; ".join(f"{i.step_id or ''} {i.message}" for i in v.issues)
                    )
            except (store.StoreError, mb.BundleError, KeyError, ValueError) as e:
                res.accepted, res.message = False, f"refused: {e}"
                return res
            ok = self.fsm.load(req.mission_id, len(v.compiled.steps))
            if not ok:
                res.accepted, res.message = False, self.fsm.reason
                return res
            self.mission, self.manifest, self.grid, self.route, self.compiled = (
                mission,
                manifest,
                grid,
                route,
                v.compiled,
            )
            self.phase, self.turn_travelled = PHASE_INIT, 0.0
            self._log_state()
            res.accepted, res.message = True, self.fsm.reason
            return res

    def _srv_pause(self, _req, res: Trigger.Response):
        with self._lock:
            ok = self.fsm.pause()
            if ok:
                self._interrupt("paused by operator")
            res.success, res.message = ok, self.fsm.reason
            return res

    def _srv_abort(self, _req, res: Trigger.Response):
        with self._lock:
            ok = self.fsm.abort("aborted by operator")
            if ok:
                self._interrupt("aborted")
            res.success, res.message = ok, self.fsm.reason
            return res

    def _srv_resume(self, _req, res: Trigger.Response):
        with self._lock:
            ok, why = self._resume_checks()
            res.success = self.fsm.prepare_resume(ok, why)
            res.message = self.fsm.reason
            self._log_state()
            return res

    def _srv_ack(self, _req, res: Trigger.Response):
        with self._lock:
            res.success, res.message = self.fsm.ack(), self.fsm.reason
            self._log_state()
            return res

    # ---- readiness ------------------------------------------------------------------------

    def _prereqs(self) -> str | None:
        """None when everything a run needs holds; otherwise the first failure."""
        now = self._now()
        if self._loc is None or now - self._loc_t > self.loc_age:
            return "no localisation monitor"
        if self._loc.state != LocalizationState.READY:
            return f"localisation not READY ({self._loc.reason})"
        if now - self._wheels_t > self.wheels_age:
            return "wheel feedback stale"
        if self._panel is None or now - self._panel_t > self.panel_age or not self._panel.valid:
            return "panel stale or invalid"
        if self._scan is None:
            return "no scan"
        return None

    def _auto(self) -> bool:
        return self._panel is not None and self._panel.valid and self._panel.mode_auto

    def _start_gate(self) -> tuple[bool, str]:
        pose = self._pose()
        if pose is None:
            return False, "no pose"
        s = self.route.start
        d = math.hypot(pose[0] - s.x_m, pose[1] - s.y_m)
        a = abs(wrap(pose[2] - s.yaw_rad))
        if d > self.start_gate_m or a > self.start_gate_rad:
            return False, f"{d:.2f} m / {math.degrees(a):.1f} deg from the route start; reposition manually"
        return True, ""

    def _start_edge(self) -> None:
        if self.fsm.state == fsm.READY:
            gate_ok, why = self._start_gate()
            pre = self._prereqs()
            if pre:
                gate_ok, why = False, pre
            if self.fsm.start(self._auto(), gate_ok, why):
                self.phase, self.turn_travelled = PHASE_INIT, 0.0
            self._log_state()
        elif self.fsm.state in (fsm.PAUSED, fsm.BLOCKED):
            if self.fsm.start(self._auto(), True):
                self.phase = PHASE_INIT
            self._log_state()

    def _resume_checks(self) -> tuple[bool, str]:
        pre = self._prereqs()
        if pre:
            return False, pre
        if not self._auto():
            return False, "selector is not AUTO"
        if not self._wheels_still:
            return False, "vehicle is moving"
        st = self._step()
        if st is None:
            return False, "no active step"
        pose = self._pose()
        if pose is None:
            return False, "no pose"
        if st.type == STRAIGHT:
            along, cross = self._along_cross(st, pose)
            if abs(cross) > self.route.limits.cross_track_limit_m:
                return False, f"outside the corridor ({cross:+.2f} m cross-track)"
            if (
                along < -self.route.limits.position_tolerance_m
                or along > st.length_m + self.route.limits.position_tolerance_m
            ):
                return False, "not on the segment"
        else:
            if self.odom_gap:
                return False, "odometry continuity lost since the pause; abort and reposition"
        blocked = self._obstruction(st, pose)
        if blocked:
            return False, blocked
        if self.clear_since is None or self._now() - self.clear_since < self.clear_stable_s:
            return False, "clearance not stable yet"
        return True, ""

    # ---- step geometry ------------------------------------------------------------------------

    def _step(self) -> CompiledStep | None:
        if (
            self.compiled is None
            or self.fsm.step_index < 0
            or self.fsm.step_index >= len(self.compiled.steps)
        ):
            return None
        return self.compiled.steps[self.fsm.step_index]

    @staticmethod
    def _along_cross(st: CompiledStep, pose) -> tuple[float, float]:
        c, s = math.cos(st.start[2]), math.sin(st.start[2])
        dx, dy = pose[0] - st.start[0], pose[1] - st.start[1]
        return dx * c + dy * s, -dx * s + dy * c

    def _remaining_turn(self, st: CompiledStep) -> float:
        target = self.turn_target if self.turn_target is not None else st.signed_angle_rad
        return target - self.turn_travelled

    def _obstruction(self, st: CompiledStep, pose) -> str | None:
        """Scan points inside the active step's swept footprint ahead (spec §5.4)."""
        scan = self._scan
        if scan is None or self.grid is None:
            return "no scan"
        try:
            tr = self.tf_buffer.lookup_transform("map", scan.header.frame_id, rclpy.time.Time())
        except Exception:  # noqa: BLE001
            return "no laser transform"
        if st.type == STRAIGHT:
            along, _ = self._along_cross(st, pose)
            a0 = max(0.0, along)
            a1 = min(st.length_m, a0 + self.horizon)
            c, s = math.cos(st.start[2]), math.sin(st.start[2])
            p0 = (st.start[0] + c * a0, st.start[1] + s * a0, st.start[2])
            p1 = (st.start[0] + c * a1, st.start[1] + s * a1, st.start[2])
            mask = fpmod.swept_line(self.grid, self.fp, p0, p1)
        else:
            mask = fpmod.swept_rotation(self.grid, self.fp, (st.start[0], st.start[1]))
        yaw = _yaw(tr.transform.rotation)
        r = np.asarray(scan.ranges, dtype=np.float64)
        ang = scan.angle_min + np.arange(len(r)) * scan.angle_increment + yaw
        ok = np.isfinite(r) & (r > scan.range_min) & (r < scan.range_max)
        ex = tr.transform.translation.x + r[ok] * np.cos(ang[ok])
        ey = tr.transform.translation.y + r[ok] * np.sin(ang[ok])
        g = self.grid.meta
        cols = np.floor((ex - g.origin_x) / g.resolution).astype(int)
        rows = np.floor((ey - g.origin_y) / g.resolution).astype(int)
        inside = (cols >= 0) & (cols < self.grid.width) & (rows >= 0) & (rows < self.grid.height)
        # points that the MAP already explains (walls) are not obstacles; only free-space hits are
        hits = mask[rows[inside], cols[inside]] & (self.grid.data[rows[inside], cols[inside]] < 65)
        n = int(hits.sum())
        if n >= self.obstacle_points:
            self.clear_since = None
            return f"{n} scan points inside the {'line' if st.type == STRAIGHT else 'rotation'} envelope"
        if self.clear_since is None:
            self.clear_since = self._now()
        return None

    # ---- goals ---------------------------------------------------------------------------------

    def _send_follow(self, st: CompiledStep, pose) -> bool:
        along, _ = self._along_cross(st, pose)
        path = Path()
        path.header.frame_id = "map"
        path.header.stamp = self.get_clock().now().to_msg()
        for x, y, yaw in st.samples:
            if (x - st.start[0]) * math.cos(st.start[2]) + (y - st.start[1]) * math.sin(
                st.start[2]
            ) < along - 0.10:
                continue  # resume: from the current projection onwards
            ps = PoseStamped()
            ps.header = path.header
            ps.pose.position.x, ps.pose.position.y = x, y
            ps.pose.orientation.z, ps.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
            path.poses.append(ps)
        if len(path.poses) < 2:
            return False
        goal = FollowPath.Goal(path=path, controller_id="FollowPath", goal_checker_id="precise")
        return self._send(self._follow, goal)

    def _send_spin(self, st: CompiledStep, pose) -> bool:
        remaining = self._remaining_turn(st)
        if self.turn_centre is None:
            self.turn_centre = self._odom_xy
            # A Spin is relative. Fold the entry heading error into this turn (bounded, same
            # direction) so consecutive turns land on the DRAWN heading instead of stacking errors.
            entry = wrap(st.start[2] - pose[2])
            entry = max(-self.entry_corr_max, min(self.entry_corr_max, entry))
            self.turn_target = st.signed_angle_rad + entry
            remaining = self._remaining_turn(st)
            self.get_logger().info(
                f"turn start: odom {self._odom_xy}, amcl {pose[:2]}, "
                f"remaining {math.degrees(remaining):+.1f} deg"
            )
        goal = Spin.Goal()
        goal.target_yaw = float(remaining)
        allowance = st.time_allowance_s * abs(remaining) / max(abs(st.signed_angle_rad), 1e-6) + 2.0
        goal.time_allowance = Duration(seconds=allowance).to_msg()
        self.turn_acc0 = self._odom_yaw_acc
        self.turn_started_t = self._now()
        self.turn_feedback = 0.0
        return self._send(self._spin, goal)

    def _send(self, client: ActionClient, goal) -> bool:
        if not client.wait_for_server(timeout_sec=2.0):
            self._fault(f"action server {client._action_name} unavailable")
            return False
        self.goal_result, self.we_cancelled = None, False
        self.goal_run_id = self.fsm.run_id
        run_id = self.fsm.run_id
        fut = client.send_goal_async(goal, feedback_callback=lambda fb: self._on_feedback(run_id, fb))
        fut.add_done_callback(lambda f: self._on_goal_response(run_id, f))
        return True

    def _on_goal_response(self, run_id: str, fut) -> None:
        with self._lock:
            if not self.fsm.accepts(run_id):
                return
            handle = fut.result()
            if not handle.accepted:
                self._fault("action goal rejected")
                return
            self.goal_handle = handle
            handle.get_result_async().add_done_callback(lambda f: self._on_result(run_id, f))

    def _on_feedback(self, run_id: str, fb) -> None:
        if fb and hasattr(fb.feedback, "angular_distance_traveled"):
            self.turn_feedback = float(fb.feedback.angular_distance_traveled)

    def _on_result(self, run_id: str, fut) -> None:
        with self._lock:
            if not self.fsm.accepts(run_id) or run_id != self.goal_run_id:
                self.get_logger().warn(f"ignoring result of an old run {run_id}")
                return
            status = fut.result().status
            self.goal_result = {
                GoalStatus.STATUS_SUCCEEDED: "succeeded",
                GoalStatus.STATUS_CANCELED: "canceled",
            }.get(status, "aborted")
            self.goal_handle = None

    def _interrupt(self, why: str) -> None:
        """Inhibit at once (the permit drops on the next tick), then cancel the action."""
        st = self._step()
        if st is not None and st.type == ROTATE and self.turn_acc0 is not None and self.phase == PHASE_GOAL:
            self.turn_travelled += self._odom_yaw_acc - self.turn_acc0
            self.turn_acc0 = None
        self.we_cancelled = True
        if self.goal_handle is not None:
            try:
                self.goal_handle.cancel_goal_async()
            except Exception:  # noqa: BLE001
                pass
            self.goal_handle = None
        self.phase, self.paused_t, self.odom_gap = PHASE_INIT, self._now(), False
        self._log_state(why)

    def _fault(self, why: str) -> None:
        if self.fsm.fault(why):
            self._interrupt(why)

    # ---- the tick ---------------------------------------------------------------------------------

    def _tick(self) -> None:
        with self._lock:
            state = self.fsm.state
            now = self._now()
            if state in fsm.ACTIVE or state == fsm.READY:
                pre = self._prereqs()
                if pre:
                    if state == fsm.READY:
                        self.fsm.unready(pre)
                    else:
                        self._fault(pre)
                elif state in fsm.ACTIVE and not self._auto():
                    self.fsm.abort("manual takeover: selector left AUTO")
                    self._interrupt("manual takeover")
            if self.fsm.state == fsm.EXECUTING:
                self._execute(now)
            elif self.fsm.state in (fsm.PAUSED, fsm.BLOCKED):
                st, pose = self._step(), self._pose()
                if st is not None and pose is not None:
                    blocked = self._obstruction(st, pose)
                    if blocked and self.fsm.resume_prepared:
                        self.fsm.invalidate_resume(blocked)
            self._publish_permit()
            self._log_state()

    def _execute(self, now: float) -> None:
        st = self._step()
        pose = self._pose()
        if st is None or pose is None:
            self._fault("no step or no pose")
            return
        if self.phase == PHASE_INIT:
            blocked = self._obstruction(st, pose)
            if blocked:
                self.fsm.block(blocked)
                self._interrupt(blocked)
                return
            if st.type == STRAIGHT:
                if not self._send_follow(st, pose):
                    if self.fsm.state == fsm.EXECUTING:
                        # nothing left of the segment: treat as arrived, verify in settle
                        self.phase, self.settle_since = PHASE_SETTLE, None
                    return
                self.phase = PHASE_GOAL
            else:
                if not self._wheels_still:
                    return  # translation must stop before rotation
                if abs(self._remaining_turn(st)) < self.turn_tol:
                    self.phase, self.settle_since = PHASE_SETTLE, None
                    return
                if self._send_spin(st, pose):
                    self.phase = PHASE_GOAL
            return

        if self.phase == PHASE_GOAL:
            if st.type == STRAIGHT:
                along, cross = self._along_cross(st, pose)
                self.cross_track = cross
                limit = self.route.limits.cross_track_limit_m
                # After a turn the line starts with the previous stop's error plus the
                # estimator's wander during the spin; RPP pulls back onto the line within
                # a metre. Until then twice the limit (still inside the validated margin).
                allowed = limit if along > self.converge_m else 2.0 * limit
                if abs(cross) > allowed:
                    self._fault(f"cross-track {cross:+.2f} m exceeds {allowed:.2f} m at {along:.2f} m along")
                    return
                if along > st.length_m + 2 * self.route.limits.position_tolerance_m:
                    self._fault(f"passed the endpoint by {along - st.length_m:.2f} m")
                    return
            else:
                travelled = self.turn_travelled + (self._odom_yaw_acc - self.turn_acc0)
                drift = math.hypot(
                    self._odom_xy[0] - self.turn_centre[0], self._odom_xy[1] - self.turn_centre[1]
                )
                if drift > self.centre_drift_m:
                    self._fault(f"turn centre drifted {drift:.2f} m")
                    return
                if (
                    now - self.turn_started_t > 1.0
                    and travelled * st.signed_angle_rad < 0
                    and abs(travelled) > self.wrong_way
                ):
                    self._fault(f"turning the wrong way ({math.degrees(travelled):+.1f} deg)")
                    return
                target = self.turn_target if self.turn_target is not None else st.signed_angle_rad
                if abs(travelled) > abs(target) + self.turn_tol + math.radians(3.0):
                    self._fault(
                        f"turn overshot: {math.degrees(travelled):+.1f} of "
                        f"{math.degrees(st.signed_angle_rad):+.1f} deg"
                    )
                    return
            blocked = self._obstruction(st, pose)
            if blocked:
                self.fsm.block(blocked)
                self._interrupt(blocked)
                return
            if self.goal_result is None:
                return
            if self.goal_result != "succeeded":
                self._fault(f"action {self.goal_result}")
                return
            if st.type == ROTATE:
                self.turn_travelled += self._odom_yaw_acc - self.turn_acc0
                self.turn_acc0 = None
            self.phase, self.settle_since = PHASE_SETTLE, None
            return

        if self.phase == PHASE_SETTLE:
            if not self._wheels_still:
                self.settle_since = None
                return
            if self.settle_since is None:
                self.settle_since = now
                return
            if now - self.settle_since < self.settle_s:
                return
            # verify the end of the step (spec §5.2, §5.3): position/heading against the
            # estimated pose with the verification allowance; turn travel from odometry.
            d = math.hypot(pose[0] - st.end[0], pose[1] - st.end[1])
            a = abs(wrap(pose[2] - st.end[2]))
            if st.type == STRAIGHT:
                if d > self.verify_pos or a > self.verify_yaw:
                    self._fault(f"endpoint missed: {d:.3f} m / {math.degrees(a):.1f} deg")
                    return
            else:
                target = self.turn_target if self.turn_target is not None else st.signed_angle_rad
                travel_err = abs(abs(self.turn_travelled) - abs(target))
                centre = self.turn_centre or self._odom_xy
                drift = math.hypot(self._odom_xy[0] - centre[0], self._odom_xy[1] - centre[1])
                self.get_logger().info(
                    f"turn check: travelled {math.degrees(self.turn_travelled):+.1f} of "
                    f"{math.degrees(st.signed_angle_rad):+.1f} deg, heading err {math.degrees(a):.2f} deg, "
                    f"odom drift {drift:.3f} m, amcl vs expected {d:.3f} m"
                )
                if travel_err > self.turn_tol or a > self.verify_yaw or drift > self.centre_drift_m:
                    self._fault(
                        f"turn out of tolerance: travelled {math.degrees(self.turn_travelled):+.1f} of "
                        f"{math.degrees(st.signed_angle_rad):+.1f} deg, "
                        f"heading err {math.degrees(a):.1f} deg, odom drift {drift:.3f} m"
                    )
                    return
            self.get_logger().info(
                f"step {st.id} ({st.type}) done: {d:.3f} m / {math.degrees(a):.2f} deg from expected"
            )
            self.fsm.step_done()
            self.phase, self.turn_travelled, self.cross_track = PHASE_INIT, 0.0, 0.0
            self.turn_centre, self.turn_target, self.clear_since = None, None, None

    # ---- outputs ----------------------------------------------------------------------------------

    def _publish_permit(self) -> None:
        m = MotionPermit()
        m.generation = self.generation
        m.instance = self._lease_instance
        self._permit_seq += 1
        m.seq = self._permit_seq
        m.header.stamp = self.get_clock().now().to_msg()
        m.run_id = self.fsm.run_id
        st = self._step()
        if self.fsm.state == fsm.EXECUTING and self.phase == PHASE_GOAL and st is not None:
            m.source = MotionPermit.FOLLOW if st.type == STRAIGHT else MotionPermit.ROTATE
            m.enabled = True
            m.reason = f"step {st.id}"
        else:
            m.source, m.enabled, m.reason = MotionPermit.NONE, False, fsm.NAMES[self.fsm.state]
        self._permit_pub.publish(m)

    def _log_state(self, note: str = "") -> None:
        key = (self.fsm.state, self.fsm.reason, self.fsm.step_index, self.phase, self.fsm.resume_prepared)
        if key != self._last_state_key:
            self._last_state_key = key
            self.get_logger().info(
                f"{fsm.NAMES[self.fsm.state]} step {self.fsm.step_index} {self.phase}: {self.fsm.reason}"
                + (f" [{note}]" if note else "")
            )
            self._publish_state()

    def _publish_state(self) -> None:
        m = RunState()
        m.generation = self.generation
        m.header.stamp = self.get_clock().now().to_msg()
        m.state = self.fsm.state
        m.run_id, m.mission_id = self.fsm.run_id, self.fsm.mission_id
        if self.manifest is not None:
            m.map_id, m.map_revision = self.manifest.map_id, self.manifest.revision
        if self.route is not None:
            m.route_id, m.route_revision = self.route.route_id, self.route.revision
        st = self._step()
        m.step_index = self.fsm.step_index
        m.step_id, m.step_type = (st.id, st.type) if st is not None else ("", "")
        if st is not None and st.type == ROTATE:
            m.remaining_turn_rad = self._remaining_turn(st)
        m.cross_track_m = self.cross_track
        m.localization_state = self._loc.state if self._loc is not None else 0
        m.resume_prepared = self.fsm.resume_prepared
        pose = self._pose()
        if pose is not None:
            m.pose_valid, m.pose_x, m.pose_y, m.pose_yaw = True, pose[0], pose[1], pose[2]
        m.reason = self.fsm.reason
        self._state_pub.publish(m)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = RouteExecutor()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        if rclpy.ok():
            raise
    finally:
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
