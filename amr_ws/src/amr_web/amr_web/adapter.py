"""The ROS side of the web app: one rclpy node, explicit typed calls, no wheels.

Services are called with a bounded wait from Flask's request threads while a
MultiThreadedExecutor spins the node in the background. A service that is not
running (e.g. the executor before nav.launch) answers (False, "... unavailable")
instead of hanging.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

import rclpy
from geometry_msgs.msg import Point, PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Path
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from std_msgs.msg import ColorRGBA
from std_srvs.srv import Trigger
from visualization_msgs.msg import Marker, MarkerArray

from amr_interfaces.msg import LocalizationState, MappingState
from amr_interfaces.srv import RunMission, SaveMap, StartSurvey

LATCHED = QoSProfile(
    depth=1, reliability=QoSReliabilityPolicy.RELIABLE, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL
)
STATE_NAMES = {0: "IDLE", 1: "MAPPING", 2: "RETURN_REVIEW", 3: "SAVING", 4: "SAVED"}
LOC_NAMES = {0: "UNLOCALIZED", 1: "CHECKING", 2: "READY", 3: "LOST"}
RUN_NAMES = {0: "IDLE", 1: "READY", 2: "EXECUTING", 3: "PAUSED", 4: "BLOCKED", 5: "FAULT", 6: "DONE"}


def _msg_to_dict(msg) -> dict[str, Any]:
    out = {}
    for name in msg.get_fields_and_field_types():
        v = getattr(msg, name)
        if hasattr(v, "get_fields_and_field_types"):
            v = _msg_to_dict(v)
        elif isinstance(v, (list, tuple)):
            v = [x if isinstance(x, (int, float, str, bool)) else _msg_to_dict(x) for x in v]
        out[name] = v
    return out


class RosAdapter(Node):
    def __init__(self) -> None:
        super().__init__("amr_web")
        self._lock = threading.Lock()
        self._mapping: dict | None = None
        self._loc: dict | None = None
        self._run: dict | None = None
        self._mapping_t = self._loc_t = self._run_t = 0.0
        g = ReentrantCallbackGroup()
        self.create_subscription(
            MappingState, "/amr/mapping_state", self._on_mapping, LATCHED, callback_group=g
        )
        self.create_subscription(
            LocalizationState, "/amr/localization_state", self._on_loc, LATCHED, callback_group=g
        )
        try:  # T7 adds RunState; tolerate its absence so the survey pages work without it
            from amr_interfaces.msg import RunState  # noqa: PLC0415

            self.create_subscription(RunState, "/amr/run_state", self._on_run, LATCHED, callback_group=g)
        except ImportError:
            pass
        self._initialpose = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", 1)
        self._preview = self.create_publisher(Path, "/amr/route_preview", LATCHED)
        self._markers = self.create_publisher(MarkerArray, "/amr/route_markers", LATCHED)
        self._clients = {
            "survey_start": self.create_client(StartSurvey, "/amr/survey/start", callback_group=g),
            "survey_returned": self.create_client(Trigger, "/amr/survey/returned", callback_group=g),
            "survey_save": self.create_client(SaveMap, "/amr/survey/save", callback_group=g),
            "survey_abort": self.create_client(Trigger, "/amr/survey/abort", callback_group=g),
            "loc_confirm": self.create_client(Trigger, "/amr/localization/confirm", callback_group=g),
            "loc_reset": self.create_client(Trigger, "/amr/localization/reset", callback_group=g),
            "run": self.create_client(RunMission, "/amr/run_mission", callback_group=g),
            "pause": self.create_client(Trigger, "/amr/pause", callback_group=g),
            "abort": self.create_client(Trigger, "/amr/abort", callback_group=g),
            "resume": self.create_client(Trigger, "/amr/resume", callback_group=g),
            "ack": self.create_client(Trigger, "/amr/ack_fault", callback_group=g),
        }

    # ---- subscriptions --------------------------------------------------------------

    def _now(self) -> float:
        return time.monotonic()

    def _on_mapping(self, m: MappingState) -> None:
        d = _msg_to_dict(m)
        d["state_name"] = STATE_NAMES.get(m.state, str(m.state))
        with self._lock:
            self._mapping, self._mapping_t = d, self._now()

    def _on_loc(self, m: LocalizationState) -> None:
        d = _msg_to_dict(m)
        d["state_name"] = LOC_NAMES.get(m.state, str(m.state))
        with self._lock:
            self._loc, self._loc_t = d, self._now()

    def _on_run(self, m) -> None:
        d = _msg_to_dict(m)
        d["state_name"] = RUN_NAMES.get(m.state, str(m.state))
        with self._lock:
            self._run, self._run_t = d, self._now()

    def state(self) -> dict[str, Any]:
        now = self._now()
        with self._lock:
            return {
                "mapping": self._mapping,
                "mapping_age_s": (now - self._mapping_t) if self._mapping else None,
                "localization": self._loc,
                "localization_age_s": (now - self._loc_t) if self._loc else None,
                "run": self._run,
                "run_age_s": (now - self._run_t) if self._run else None,
                "t": time.time(),
            }

    # ---- services ------------------------------------------------------------------

    def _call(self, key: str, req, timeout: float = 30.0):
        client = self._clients[key]
        if not client.wait_for_service(timeout_sec=0.5):
            return None
        fut = client.call_async(req)
        deadline = time.monotonic() + timeout
        while not fut.done():
            if time.monotonic() > deadline:
                return None
            time.sleep(0.02)
        return fut.result()

    def _trigger(self, key: str) -> tuple[bool, str]:
        r = self._call(key, Trigger.Request())
        if r is None:
            return False, f"{self._clients[key].srv_name} unavailable"
        return bool(r.success), r.message

    def survey_start(self, map_id: str, description: str) -> tuple[bool, str]:
        r = self._call("survey_start", StartSurvey.Request(map_id=map_id, description=description))
        return (False, "survey service unavailable") if r is None else (bool(r.accepted), r.message)

    def survey_returned(self) -> tuple[bool, str]:
        return self._trigger("survey_returned")

    def survey_save(self, note: str) -> tuple[bool, str]:
        r = self._call("survey_save", SaveMap.Request(note=note), timeout=60.0)
        return (False, "survey service unavailable") if r is None else (bool(r.ok), r.message)

    def survey_abort(self) -> tuple[bool, str]:
        return self._trigger("survey_abort")

    def localization_confirm(self) -> tuple[bool, str]:
        return self._trigger("loc_confirm")

    def localization_reset(self) -> tuple[bool, str]:
        return self._trigger("loc_reset")

    def set_initial_pose(self, x: float, y: float, yaw: float) -> tuple[bool, str]:
        """Operator estimate (spec §4.2): wide covariance, AMCL refines it."""
        with self._lock:
            run = self._run
        if run and run.get("state_name") == "EXECUTING":
            return False, "refused: a route is executing (no /initialpose during a segment)"
        m = PoseWithCovarianceStamped()
        m.header.frame_id = "map"
        m.header.stamp = self.get_clock().now().to_msg()
        m.pose.pose.position.x, m.pose.pose.position.y = x, y
        m.pose.pose.orientation.z, m.pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        m.pose.covariance[0] = m.pose.covariance[7] = 0.5**2
        m.pose.covariance[35] = math.radians(15.0) ** 2
        self._initialpose.publish(m)
        return (
            True,
            f"initial pose ({x:.2f}, {y:.2f}, {math.degrees(yaw):.0f} deg) sent; drive slowly, then confirm",
        )

    def publish_route_preview(self, compiled, frame_id: str) -> None:
        path = Path()
        path.header.frame_id = frame_id
        path.header.stamp = self.get_clock().now().to_msg()
        markers = MarkerArray()
        clear = Marker()
        clear.action = Marker.DELETEALL
        markers.markers.append(clear)
        for i, st in enumerate(compiled.steps):
            if st.type == "straight":
                for x, y, yaw in st.samples:
                    p = PoseStamped()
                    p.header = path.header
                    p.pose.position.x, p.pose.position.y = x, y
                    p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
                    path.poses.append(p)
            else:
                m = Marker()
                m.header = path.header
                m.ns, m.id = "turns", i
                m.type, m.action = Marker.TEXT_VIEW_FACING, Marker.ADD
                m.pose.position = Point(x=st.start[0], y=st.start[1], z=0.3)
                m.pose.orientation.w = 1.0
                m.scale.z = 0.3
                m.color = ColorRGBA(r=1.0, g=0.6, b=0.0, a=1.0)
                deg = abs(math.degrees(st.signed_angle_rad))
                m.text = f"{st.id}: {'CCW' if st.signed_angle_rad > 0 else 'CW'} {deg:.0f}"
                markers.markers.append(m)
        self._preview.publish(path)
        self._markers.publish(markers)

    def run_mission(self, mission_id: str) -> tuple[bool, str]:
        r = self._call("run", RunMission.Request(mission_id=mission_id))
        return (
            (False, "executor unavailable (nav.launch.py not running?)")
            if r is None
            else (bool(r.accepted), r.message)
        )

    def pause(self) -> tuple[bool, str]:
        return self._trigger("pause")

    def abort(self) -> tuple[bool, str]:
        return self._trigger("abort")

    def prepare_resume(self) -> tuple[bool, str]:
        return self._trigger("resume")

    def ack_fault(self) -> tuple[bool, str]:
        return self._trigger("ack")


def start_spinning(adapter: RosAdapter) -> threading.Thread:
    executor = rclpy.executors.MultiThreadedExecutor(num_threads=4)
    executor.add_node(adapter)
    t = threading.Thread(target=executor.spin, name="ros", daemon=True)
    t.start()
    return t
