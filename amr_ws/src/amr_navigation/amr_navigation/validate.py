"""Route validation against a map bundle (spec §6.3, §6.4, §5.4). Errors, never warnings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from amr_maps import grid as gridio
from amr_navigation import footprint as fpmod
from amr_navigation.compiler import STRAIGHT, CompiledRoute, compile_route
from amr_navigation.route import Route, RouteError


@dataclass
class Issue:
    code: str
    message: str
    step_id: str | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "step_id": self.step_id}


@dataclass
class Validation:
    issues: list[Issue]
    compiled: CompiledRoute | None

    @property
    def ok(self) -> bool:
        return not self.issues and self.compiled is not None


def load_keepout(rev_dir: str) -> gridio.Grid | None:
    path = os.path.join(rev_dir, "keepout.yaml")
    return gridio.read(path) if os.path.isfile(path) else None


def validate(
    route: Route,
    manifest,
    grid: gridio.Grid,
    fp: fpmod.Footprint,
    keepout: gridio.Grid | None = None,
) -> Validation:
    issues: list[Issue] = []
    if route.map.id != manifest.map_id or route.map.revision != manifest.revision:
        issues.append(
            Issue(
                "map_ref",
                f"route is for map {route.map.id}/rev{route.map.revision}, "
                f"loaded {manifest.map_id}/rev{manifest.revision}",
            )
        )
    elif route.map.sha256 != manifest.sha256:
        issues.append(
            Issue(
                "map_hash", "map bundle hash differs: the map was re-saved, re-validate on the new revision"
            )
        )
    if not route.route_id or "/" in route.route_id or route.route_id.startswith("."):
        issues.append(Issue("route_id", "route_id must be a plain name"))
    if route.repeat_count < 1:
        issues.append(Issue("repeat", "repeat_count must be a positive integer"))
    try:
        compiled = compile_route(route)
    except RouteError as e:
        issues.append(Issue("geometry", str(e), e.step_id))
        return Validation(issues, None)

    if route.repeat_count > 1 and not compiled.closes:
        issues.append(
            Issue(
                "repeat",
                "repeat_count > 1 needs the route to end where it starts (within tolerance); "
                "add an explicit return sequence",
            )
        )
    # Start pose itself must be clear (the vehicle stands there).
    c = fpmod.check(grid, fpmod.swept_rotation(grid, fp, (route.start.x_m, route.start.y_m)), keepout)
    if not c.clear:
        issues.append(
            Issue(
                "clearance",
                f"start pose not clear: {c.occupied} occupied, {c.unknown} unknown, "
                f"{c.keepout} keepout cells",
            )
        )
    for st in compiled.steps:
        if st.type == STRAIGHT:
            mask = fpmod.swept_line(grid, fp, st.start, st.end)
        else:
            mask = fpmod.swept_rotation(grid, fp, (st.start[0], st.start[1]))
        c = fpmod.check(grid, mask, keepout)
        if not c.clear:
            what = "line" if st.type == STRAIGHT else "rotation sweep"
            issues.append(
                Issue(
                    "clearance",
                    f"{what} not clear: {c.occupied} occupied, {c.unknown} unknown, "
                    f"{c.keepout} keepout cells (margin included)",
                    st.id,
                )
            )
    return Validation(issues, compiled)
