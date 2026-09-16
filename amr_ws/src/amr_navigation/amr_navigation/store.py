"""Route and mission revisions on disk, next to the map bundles.

    <maps_dir>/<map_id>/routes/<route_id>/rev<N>.yaml     immutable once written
    <maps_dir>/missions/<mission_id>.yaml                  one validated route revision

A route revision is written to a temp file and renamed, and never overwritten.
"""

from __future__ import annotations

import hashlib
import os
import re
import time

import yaml

from amr_navigation.route import Route

REV_RE = re.compile(r"^rev(\d+)\.yaml$")


class StoreError(RuntimeError):
    pass


def routes_dir(maps_dir: str, map_id: str, route_id: str | None = None) -> str:
    d = os.path.join(maps_dir, map_id, "routes")
    return os.path.join(d, route_id) if route_id else d


def list_routes(maps_dir: str, map_id: str) -> dict[str, list[int]]:
    d = routes_dir(maps_dir, map_id)
    out: dict[str, list[int]] = {}
    if not os.path.isdir(d):
        return out
    for rid in sorted(os.listdir(d)):
        revs = sorted(int(m.group(1)) for f in os.listdir(os.path.join(d, rid)) if (m := REV_RE.match(f)))
        if revs:
            out[rid] = revs
    return out


def route_path(maps_dir: str, map_id: str, route_id: str, revision: int) -> str:
    return os.path.join(routes_dir(maps_dir, map_id, route_id), f"rev{revision}.yaml")


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def save_route(maps_dir: str, route: Route) -> tuple[int, str, str]:
    """Assign the next revision, write atomically. Returns (revision, path, sha256)."""
    revs = list_routes(maps_dir, route.map.id).get(route.route_id, [])
    revision = (revs[-1] + 1) if revs else 1
    route.revision = revision
    d = routes_dir(maps_dir, route.map.id, route.route_id)
    os.makedirs(d, exist_ok=True)
    dest = route_path(maps_dir, route.map.id, route.route_id, revision)
    if os.path.exists(dest):
        raise StoreError(f"route revision exists: {dest}")
    tmp = dest + f".tmp-{os.getpid()}"
    with open(tmp, "w") as fh:
        fh.write(route.dumps())
    os.rename(tmp, dest)
    return revision, dest, sha256_file(dest)


def load_route(maps_dir: str, map_id: str, route_id: str, revision: int) -> tuple[Route, str]:
    path = route_path(maps_dir, map_id, route_id, revision)
    if not os.path.isfile(path):
        raise StoreError(f"no such route revision: {path}")
    with open(path) as fh:
        return Route.loads(fh.read()), sha256_file(path)


# ---- missions --------------------------------------------------------------


def missions_dir(maps_dir: str) -> str:
    return os.path.join(maps_dir, "missions")


def list_missions(maps_dir: str) -> list[dict]:
    d = missions_dir(maps_dir)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".yaml"):
            with open(os.path.join(d, f)) as fh:
                out.append(yaml.safe_load(fh))
    return out


def save_mission(
    maps_dir: str,
    mission_id: str,
    map_id: str,
    map_revision: int,
    map_sha256: str,
    route_id: str,
    route_revision: int,
    route_sha256: str,
) -> str:
    if not mission_id or "/" in mission_id or mission_id.startswith("."):
        raise StoreError("mission_id must be a plain name")
    os.makedirs(missions_dir(maps_dir), exist_ok=True)
    path = os.path.join(missions_dir(maps_dir), f"{mission_id}.yaml")
    doc = {
        "mission_id": mission_id,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "map": {"id": map_id, "revision": map_revision, "sha256": map_sha256},
        "route": {"id": route_id, "revision": route_revision, "sha256": route_sha256},
    }
    tmp = path + f".tmp-{os.getpid()}"
    with open(tmp, "w") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False)
    os.rename(tmp, path)
    return path


def load_mission(maps_dir: str, mission_id: str) -> dict:
    path = os.path.join(missions_dir(maps_dir), f"{mission_id}.yaml")
    if not os.path.isfile(path):
        raise StoreError(f"no such mission: {mission_id}")
    with open(path) as fh:
        return yaml.safe_load(fh)
