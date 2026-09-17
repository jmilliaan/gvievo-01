"""Map revision bundles: staged, verified, published atomically (spec §6.2).

Layout under maps_dir:

    <map_id>/rev<N>/map.pgm, map.yaml        occupancy, nav2 map_server format
                    posegraph.posegraph,     slam_toolbox serialisation (+ .data)
                    posegraph.data
                    manifest.yaml            hashes, geometry, start reference, review
    <map_id>/.staging-<N>-<pid>/             work in progress; never a revision

A revision exists only once the rename from staging has happened, so a
partial save can never look approved. Revisions are never rewritten:
publish() refuses if rev<N> already exists. Pure filesystem + numpy; no ROS.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field

import yaml

from amr_maps import grid as gridio

MANIFEST = "manifest.yaml"
REV_RE = re.compile(r"^rev(\d+)$")


class BundleError(RuntimeError):
    pass


@dataclass
class StartReference:
    x_m: float
    y_m: float
    yaw_rad: float
    description: str


@dataclass
class ReturnReview:
    dx_m: float
    dy_m: float
    dyaw_rad: float
    note: str = ""


@dataclass
class Manifest:
    map_id: str
    revision: int
    created: str
    frame_id: str
    resolution: float
    origin: list[float]
    width: int
    height: int
    start: dict
    review: dict
    files: dict = field(default_factory=dict)  # name -> sha256
    software: dict = field(default_factory=dict)
    sha256: str = ""  # over the files table, the bundle identity routes refer to


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_revisions(maps_dir: str, map_id: str) -> list[int]:
    d = os.path.join(maps_dir, map_id)
    if not os.path.isdir(d):
        return []
    revs = []
    for name in os.listdir(d):
        m = REV_RE.match(name)
        if m and os.path.isfile(os.path.join(d, name, MANIFEST)):
            revs.append(int(m.group(1)))
    return sorted(revs)


def next_revision(maps_dir: str, map_id: str) -> int:
    revs = list_revisions(maps_dir, map_id)
    return (revs[-1] + 1) if revs else 1


def revision_dir(maps_dir: str, map_id: str, revision: int) -> str:
    return os.path.join(maps_dir, map_id, f"rev{revision}")


def staging_dir(maps_dir: str, map_id: str, revision: int) -> str:
    d = os.path.join(maps_dir, map_id, f".staging-{revision}-{os.getpid()}")
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    return d


def write_manifest(stage: str, manifest: Manifest) -> None:
    doc = asdict(manifest)
    with open(os.path.join(stage, MANIFEST), "w") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False)


def bundle_hash(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(f"{name}:{files[name]}\n".encode())
    return h.hexdigest()


def stage_bundle(
    stage: str,
    grid: gridio.Grid,
    posegraph_stem: str | None,
    manifest: Manifest,
    required_posegraph: bool = True,
) -> Manifest:
    """Write map files into `stage`, hash them, write the manifest. Raises on any gap."""
    gridio.write(grid, os.path.join(stage, "map"))
    if posegraph_stem is not None:
        for ext in (".posegraph", ".data"):
            src = posegraph_stem + ext
            if not os.path.isfile(src):
                if required_posegraph:
                    raise BundleError(f"slam serialisation missing: {src}")
                continue
            dst = os.path.join(stage, "posegraph" + ext)
            if not (os.path.exists(dst) and os.path.samefile(src, dst)):
                shutil.copy2(src, dst)  # slam_toolbox may have written straight into the stage
    elif required_posegraph:
        raise BundleError("no pose graph serialised")
    files = {}
    for name in sorted(os.listdir(stage)):
        if name == MANIFEST:
            continue
        path = os.path.join(stage, name)
        if os.path.getsize(path) == 0:
            raise BundleError(f"empty file in bundle: {name}")
        files[name] = sha256_file(path)
    manifest.files = files
    manifest.sha256 = bundle_hash(files)
    write_manifest(stage, manifest)
    return manifest


def verify(stage: str) -> Manifest:
    """Re-read the manifest and re-hash every listed file. Raises on mismatch."""
    with open(os.path.join(stage, MANIFEST)) as fh:
        doc = yaml.safe_load(fh)
    m = Manifest(**doc)
    for name, digest in m.files.items():
        path = os.path.join(stage, name)
        if not os.path.isfile(path):
            raise BundleError(f"listed file missing: {name}")
        if sha256_file(path) != digest:
            raise BundleError(f"hash mismatch: {name}")
    if bundle_hash(m.files) != m.sha256:
        raise BundleError("bundle hash mismatch")
    for required in ("map.pgm", "map.yaml"):
        if required not in m.files:
            raise BundleError(f"bundle lacks {required}")
    _read_grid(os.path.join(stage, "map.yaml"))  # must parse
    return m


def _read_grid(path: str) -> gridio.Grid:
    """A malformed or unsupported (e.g. rotated-origin) grid is a bad bundle, not a crash."""
    try:
        return gridio.read(path)
    except (gridio.GridError, OSError) as e:
        raise BundleError(f"map grid: {e}") from e


def publish(stage: str, maps_dir: str, map_id: str, revision: int) -> str:
    """Atomic rename of a verified stage to rev<N>. Refuses to overwrite."""
    dest = revision_dir(maps_dir, map_id, revision)
    if os.path.exists(dest):
        raise BundleError(f"revision already exists: {dest}")
    os.rename(stage, dest)
    return dest


def discard(stage: str) -> None:
    shutil.rmtree(stage, ignore_errors=True)


def load(maps_dir: str, map_id: str, revision: int) -> tuple[Manifest, gridio.Grid]:
    d = revision_dir(maps_dir, map_id, revision)
    if not os.path.isdir(d):
        raise BundleError(f"no such revision: {d}")
    m = verify(d)
    return m, _read_grid(os.path.join(d, "map.yaml"))


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
