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


# Files the navigation stack consumes from a revision besides the listed ones. If present
# they must be listed too, or the bundle identity would not cover what is actually used.
CONSUMED_OPTIONAL = ("keepout.yaml", "keepout.pgm")


def _contained(stage: str, name: str) -> str:
    """The path of a bundle member, refusing anything that escapes the revision directory:
    absolute names, traversal, and symlinks to elsewhere (review Q14)."""
    if not name or os.path.isabs(name) or os.path.normpath(name) != name or name.startswith(("../", "./")):
        raise BundleError(f"bundle member name not contained: {name!r}")
    if os.sep in name or (os.altsep and os.altsep in name):
        raise BundleError(f"bundle member must be a plain file name: {name!r}")
    path = os.path.join(stage, name)
    if os.path.islink(path):
        raise BundleError(f"bundle member is a symlink: {name}")
    root = os.path.realpath(stage)
    if os.path.commonpath([root, os.path.realpath(path)]) != root:
        raise BundleError(f"bundle member resolves outside the revision: {name}")
    return path


def _image_of(stage: str, yaml_name: str) -> str:
    """The `image` a map yaml points at, as a bundle member name (must be contained)."""
    with open(os.path.join(stage, yaml_name)) as fh:
        doc = yaml.safe_load(fh) or {}
    image = str(doc.get("image", ""))
    if os.path.isabs(image) or os.path.dirname(image):
        raise BundleError(f"{yaml_name} image must be a plain file name inside the bundle: {image!r}")
    return image


def verify(stage: str) -> Manifest:
    """Re-read the manifest and re-hash every listed file. Raises on mismatch.

    The bundle identity (sha256 over the file table) must cover every byte navigation
    consumes (review Q14): listed names are contained plain files, the map yaml's image
    is a listed file, optional keepout files present in the directory are listed, and
    the manifest geometry is the loaded grid's.
    """
    with open(os.path.join(stage, MANIFEST)) as fh:
        doc = yaml.safe_load(fh)
    m = Manifest(**doc)
    if not isinstance(m.files, dict) or not m.files:
        raise BundleError("manifest file table missing or empty")
    for name, digest in m.files.items():
        if not (isinstance(name, str) and isinstance(digest, str)):
            raise BundleError("manifest file table must map file names to hex digests")
        path = _contained(stage, name)
        if not os.path.isfile(path):
            raise BundleError(f"listed file missing: {name}")
        if sha256_file(path) != digest:
            raise BundleError(f"hash mismatch: {name}")
    if bundle_hash(m.files) != m.sha256:
        raise BundleError("bundle hash mismatch")
    for required in ("map.pgm", "map.yaml"):
        if required not in m.files:
            raise BundleError(f"bundle lacks {required}")
    image = _image_of(stage, "map.yaml")
    if image not in m.files:
        raise BundleError(f"map.yaml image {image!r} is not a listed bundle file")
    for name in CONSUMED_OPTIONAL:
        if os.path.lexists(os.path.join(stage, name)) and name not in m.files:
            raise BundleError(f"{name} is present but not listed in the manifest")
    if "keepout.yaml" in m.files and _image_of(stage, "keepout.yaml") not in m.files:
        raise BundleError("keepout.yaml image is not a listed bundle file")
    grid = _read_grid(os.path.join(stage, "map.yaml"))  # must parse
    geom = (int(m.width), int(m.height), float(m.resolution), [float(v) for v in m.origin[:2]])
    actual = (grid.width, grid.height, grid.meta.resolution, [grid.meta.origin_x, grid.meta.origin_y])
    if (
        geom[0] != actual[0]
        or geom[1] != actual[1]
        or abs(geom[2] - actual[2]) > 1e-9
        or any(abs(a - b) > 1e-6 for a, b in zip(geom[3], actual[3], strict=True))
    ):
        raise BundleError(f"manifest geometry {geom} does not match the map grid {actual}")
    return m


def _read_grid(path: str) -> gridio.Grid:
    """A malformed or unsupported (e.g. rotated-origin) grid is a bad bundle, not a crash."""
    try:
        return gridio.read(path)
    except (gridio.GridError, OSError) as e:
        raise BundleError(f"map grid: {e}") from e


def derive_revision(maps_dir: str, map_id: str, from_revision: int, extra: dict[str, str]) -> tuple[str, int]:
    """A NEW revision = a verified revision's files plus `extra` {bundle name: source path},
    e.g. a keepout mask. Revisions are immutable and their identity covers every consumed
    file (review Q14), so adding a keepout is a new revision, never an edit; missions
    referencing the old one keep meaning exactly what they meant. Returns (path, revision)."""
    src_dir = revision_dir(maps_dir, map_id, from_revision)
    m = verify(src_dir)
    revision = next_revision(maps_dir, map_id)
    stage = staging_dir(maps_dir, map_id, revision)
    for name in m.files:
        shutil.copy2(os.path.join(src_dir, name), os.path.join(stage, name))
    for name, path in extra.items():
        _contained(stage, name)
        shutil.copy2(path, os.path.join(stage, name))
    files = {n: sha256_file(os.path.join(stage, n)) for n in sorted(os.listdir(stage)) if n != MANIFEST}
    m.revision, m.created, m.files, m.sha256 = revision, now_iso(), files, bundle_hash(files)
    write_manifest(stage, m)
    try:
        verify(stage)
    except BundleError:
        discard(stage)
        raise
    return publish(stage, maps_dir, map_id, revision), revision


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
