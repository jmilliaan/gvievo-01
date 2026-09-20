"""The layout itself: filesystem anchors and the package boundary.

Two failure modes this refactor introduced, both silent:

  * a module that computes a path from its own __file__ points somewhere new
    the moment it moves directory. Nothing raises - run logs simply start
    landing in agv_core/logs/ and the numbering restarts at 0001 beside the
    real runs. Only a check that pins the resolved path catches that.

  * the vehicle library is imported by two very different runtimes - the ROS
    nodes under amr_ws/ and the legacy standalone controller - so it may not
    depend on either. A stray `import flask` or `import rclpy` inside agv_core
    breaks the other runtime at import time, on the vehicle, not here.

Until 2026-09-20 this file pinned the opposite arrangement: core/, drivers/,
drivers/canbus/ and app/ went on sys.path rather than becoming packages, which
made module BASENAMES one flat namespace where two modules could never share a
name. That is gone. agv_core is a real package, imports state where a module
lives, and what needs pinning now is the package boundary instead.
"""
import ast
import pathlib
import sys

from helpers import ROOT, check

from agv_core import config, runlog

# Directories that must NOT come back as sys.path layers.
RETIRED_LAYER_DIRS = ["core", "drivers", "drivers/canbus"]
PKG = ROOT / "agv_core"


def test_path_anchors():
    """Directory-dependent paths must resolve to the repo root, not to the
    directory the module happens to live in today."""
    print("\nfilesystem anchors survive the move")

    check("config.PROFILE_DIR points at the repo root",
          pathlib.Path(config.PROFILE_DIR).resolve()
          == (ROOT / "profiles").resolve(), config.PROFILE_DIR)

    check("the profile resolves under profiles/",
          pathlib.Path(config.profile_path()).parent.resolve()
          == (ROOT / "profiles").resolve())

    # runlog moved from core/ to agv_core/ - the same depth, so LOG_DIR still
    # lands on the root. Pinned because the next move may not preserve it.
    check("runlog.LOG_DIR points at the repo root",
          pathlib.Path(runlog.LOG_DIR).resolve() == (ROOT / "logs").resolve(),
          runlog.LOG_DIR)


def test_the_library_is_a_package():
    """agv_core is imported by package path, from anywhere, exactly once."""
    print("\nthe vehicle library is a real package")

    for d in ["", "drivers", "drivers/canbus"]:
        sub = PKG / d if d else PKG
        check(f"agv_core/{d} is a package" if d else "agv_core is a package",
              (sub / "__init__.py").is_file(), str(sub))

    check("the retired layer directories are gone",
          not any((ROOT / d).exists() for d in RETIRED_LAYER_DIRS),
          str([d for d in RETIRED_LAYER_DIRS if (ROOT / d).exists()]))

    # A module reachable under two names is the hazard the flat namespace had
    # and the package was supposed to end: it would be imported twice, with two
    # copies of its module-level state (config's loaded profile, ownerlock's
    # handles). The repo root on sys.path is what makes agv_core importable;
    # the package's own directories must never join it.
    inside = {PKG.resolve(), (PKG / "drivers").resolve(),
              (PKG / "drivers" / "canbus").resolve()}
    on_path = [p for p in sys.path if p and pathlib.Path(p).resolve() in inside]
    check("no agv_core directory is itself on sys.path", not on_path, str(on_path))

    names = sorted(f.stem for f in PKG.rglob("*.py") if not f.stem.startswith("_"))
    shadowed = sorted(set(names) & set(sys.stdlib_module_names))
    check("no library module shadows a standard library module",
          not shadowed, str(shadowed))


def _imported_modules(path):
    """Every absolute module name imported anywhere in a file, lazy ones too."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.lineno, node.module


def test_the_library_depends_on_neither_runtime():
    """agv_core is shared by the ROS stack and the legacy controller, so it may
    import neither ROS nor Flask - at any nesting level, lazily or not."""
    print("\nthe vehicle library stays runtime-neutral")

    forbidden = {"rclpy", "rcl_interfaces", "geometry_msgs", "nav_msgs",
                 "sensor_msgs", "std_msgs", "amr_interfaces", "amr_base",
                 "flask", "werkzeug", "jinja2", "canworker", "app"}
    offenders = []
    for f in sorted(PKG.rglob("*.py")):
        for lineno, mod in _imported_modules(f):
            if mod.split(".")[0] in forbidden:
                offenders.append(f"{f.relative_to(ROOT)}:{lineno} {mod}")
    check("agv_core imports neither ROS nor Flask nor the legacy controller",
          not offenders, "; ".join(offenders[:3]))

    # Bare sibling imports are what the package replaced. One creeping back in
    # resolves only when something else has put that directory on sys.path,
    # which is precisely the accident-by-path-order this layout removed.
    local = {f.stem for f in PKG.rglob("*.py")} - {"__init__"}
    bare = [f"{f.relative_to(ROOT)}:{lineno} {mod}"
            for f in sorted(PKG.rglob("*.py"))
            for lineno, mod in _imported_modules(f)
            if mod.split(".")[0] in local]
    check("no module inside agv_core imports a sibling by bare name",
          not bare, "; ".join(bare[:3]))


def test_entry_point():
    """main.py is what systemd runs, so it has to work from the repo root and
    carry no logic of its own."""
    print("\nthe entry point resolves")

    src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("main.py imports the server", "from app.server import main" in src)
    check("main.py stays thin", len(src.splitlines()) < 40,
          f"{len(src.splitlines())} lines")
    # The path surgery is what the package removed. If it comes back here, the
    # flat namespace comes back with it.
    check("main.py does no sys.path surgery", "sys.path.insert" not in src)

    # app/server.py, not app/app.py: the module is the server, so it is called
    # server, and `from app.server import main` reads as what it does.
    check("the Flask module is not named app.py",
          not (ROOT / "app" / "app.py").exists())
    check("Flask finds its templates under app/",
          (ROOT / "app" / "templates" / "base.html").exists()
          and (ROOT / "app" / "static" / "common.js").exists())


def test_assets_are_offline():
    """Nothing the UI needs may be fetched over the network.

    The vehicle has no internet on the floor. A CDN font link renders correctly
    at a desk and silently falls back to system fonts on the AGV - the page
    still WORKS, so nobody notices until they are standing next to it, which is
    exactly the kind of regression worth a source scan.
    """
    import re
    print("\nweb assets are self-contained")

    static = ROOT / "app" / "static"
    tpl = ROOT / "app" / "templates"
    remote = re.compile(
        r'(<link[^>]*https?:)|(<script[^>]*src=["\']https?:)'
        r'|(@import[^;]*https?:)|(url\(\s*["\']?https?:)', re.I)

    for f in sorted(list(tpl.glob("*.html")) + list(static.glob("*.css"))
                    + list(static.glob("*.js"))):
        hits = remote.findall(f.read_text(encoding="utf-8"))
        check(f"{f.name} loads nothing remotely", not hits, str(hits[:1]))

    css = (static / "app.css").read_text(encoding="utf-8")
    faces = re.findall(r'src:\s*url\(["\']?([^"\')]+)', css)
    check("app.css declares the self-hosted faces", len(faces) >= 8, str(len(faces)))
    for rel in faces:
        check(f"{rel} is present", (static / rel).is_file())

    # The families named in the stack must be the ones actually shipped, or the
    # @font-face block is decoration and the browser silently uses the fallback.
    for fam in ("Archivo", "IBM Plex Sans", "IBM Plex Mono"):
        # Tolerate whitespace after the colon rather than stripping it out of
        # the whole file - the family names contain spaces themselves.
        check(f"{fam} is declared and bundled",
              re.search(rf'font-family:\s*"{re.escape(fam)}"', css) is not None)


TESTS = [
    test_path_anchors,
    test_the_library_is_a_package,
    test_the_library_depends_on_neither_runtime,
    test_entry_point,
    test_assets_are_offline,
]
