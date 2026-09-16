"""The canonical route artefact (spec §6.4): editor and executor share it.

Human-readable degrees and cw/ccw in the file; the compiler converts to SI.
A route belongs to one map bundle revision, named by id, revision AND sha256,
so a re-surveyed map invalidates every route drawn on the old one.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import yaml

SCHEMA_VERSION = 1
ALLOWED_ANGLES_DEG = (45, 90, 180, 270)
DIRECTIONS = ("cw", "ccw")
STRAIGHT, ROTATE = "straight", "rotate"


class RouteError(ValueError):
    """A route that cannot be compiled. `step_id` names the offending step when known."""

    def __init__(self, message: str, step_id: str | None = None):
        super().__init__(message)
        self.step_id = step_id


@dataclass
class MapRef:
    id: str
    revision: int
    sha256: str


@dataclass
class StartPose:
    x_m: float
    y_m: float
    yaw_deg: float

    @property
    def yaw_rad(self) -> float:
        return math.radians(self.yaw_deg)


@dataclass
class Limits:
    linear_mps: float = 0.30  # spec §5.2 initial cap
    angular_rad_s: float = 0.30  # spec §5.3 initial cap
    position_tolerance_m: float = 0.05
    heading_tolerance_deg: float = 2.0
    cross_track_limit_m: float = 0.10


@dataclass
class Step:
    id: str
    type: str  # STRAIGHT | ROTATE
    to: tuple[float, float] | None = None  # straight: end point (x_m, y_m)
    direction: str | None = None  # rotate: cw | ccw
    angle_deg: float | None = None  # rotate: 45 | 90 | 180 | 270

    def to_dict(self) -> dict:
        if self.type == STRAIGHT:
            return {"id": self.id, "type": STRAIGHT, "to": {"x_m": self.to[0], "y_m": self.to[1]}}
        return {"id": self.id, "type": ROTATE, "direction": self.direction, "angle_deg": self.angle_deg}

    @staticmethod
    def from_dict(d: dict) -> Step:
        t = d.get("type")
        if t == STRAIGHT:
            to = d.get("to") or {}
            return Step(
                str(d.get("id", "")), STRAIGHT, to=(float(to.get("x_m", 0.0)), float(to.get("y_m", 0.0)))
            )
        if t == ROTATE:
            return Step(
                str(d.get("id", "")),
                ROTATE,
                direction=d.get("direction"),
                angle_deg=float(d["angle_deg"]) if "angle_deg" in d else None,
            )
        raise RouteError(f"unknown step type {t!r}", str(d.get("id", "")))


@dataclass
class Route:
    route_id: str
    map: MapRef
    start: StartPose
    steps: list[Step] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)
    revision: int = 0  # 0 = unsaved draft
    repeat_count: int = 1
    frame_id: str = "map"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "route_id": self.route_id,
            "revision": self.revision,
            "map": asdict(self.map),
            "frame_id": self.frame_id,
            "start": asdict(self.start),
            "limits": asdict(self.limits),
            "steps": [s.to_dict() for s in self.steps],
            "repeat_count": self.repeat_count,
        }

    @staticmethod
    def from_dict(d: dict) -> Route:
        if int(d.get("schema_version", 0)) != SCHEMA_VERSION:
            raise RouteError(f"schema_version must be {SCHEMA_VERSION}")
        m = d.get("map") or {}
        st = d.get("start") or {}
        return Route(
            route_id=str(d.get("route_id", "")),
            revision=int(d.get("revision", 0)),
            map=MapRef(str(m.get("id", "")), int(m.get("revision", 0)), str(m.get("sha256", ""))),
            frame_id=str(d.get("frame_id", "map")),
            start=StartPose(
                float(st.get("x_m", 0.0)), float(st.get("y_m", 0.0)), float(st.get("yaw_deg", 0.0))
            ),
            limits=Limits(**{k: float(v) for k, v in (d.get("limits") or {}).items()}),
            steps=[Step.from_dict(s) for s in d.get("steps") or []],
            repeat_count=int(d.get("repeat_count", 1)),
        )

    def dumps(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @staticmethod
    def loads(text: str) -> Route:
        return Route.from_dict(yaml.safe_load(text) or {})
