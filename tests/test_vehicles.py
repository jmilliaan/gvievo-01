"""Two vehicles, one branch (manuals/agv-02-plan.md): every profile in the repo, the local selector
(amr_ws/env/vehicle.sh reading $AMR_STATE_DIR/vehicle.env), the host-name check (agv_core.identity),
and the suite itself always testing the reference profile, agv-01, on either PC."""
import glob
import json
import os
import subprocess
import tempfile

from helpers import ROOT, check

from agv_core import config, identity, mission


def test_every_profile():
    print("\nevery vehicle's profile")
    paths = sorted(glob.glob(os.path.join(config.PROFILE_DIR, "*.json")))
    names = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    check("both vehicles have a profile in the repo", {"agv-01", "agv-02"} <= set(names), names)
    serials, problems = {}, []
    try:
        for path, name in zip(paths, names, strict=True):
            try:
                ns = config.load(path)
            except config.ConfigError as e:
                problems.append(f"{name}: {e}")
                continue
            serials.setdefault(ns["STATION_SERIAL_NUMBER"], []).append(name)
            site = ns["TAPE_LOC_SITE_MISSION"]
            needs = ns["TAPE_LOC_LIVE"] or ns["STATION_ENABLED"]
            exists = os.path.exists(os.path.join(mission.MISSION_DIR, f"{site}.json"))
            if needs and not exists:
                problems.append(f"{name}: live or station on, but its site mission {site} is missing")
            if exists:
                try:
                    m = mission.load_site(site)
                    circuit = ns["TAPE_LOC_SHADOW_CIRCUIT"]
                    if circuit not in m["CIRCUITS"]:
                        problems.append(f"{name}: shadow_circuit {circuit} not in {site}")
                except mission.MissionError as e:
                    problems.append(f"{name}: site mission {site}: {e}")
    finally:
        config.load()
    check("every profile loads, and its site mission loads where one is needed or present",
          not problems, "; ".join(problems))
    check("no two profiles share a station serial number (MQTT topics)",
          all(len(v) == 1 for v in serials.values()), serials)
    check("the reference profile is loaded again afterwards", config.PROFILE_NAME == "agv-01",
          config.PROFILE_NAME)


def test_identity():
    print("\nwhich vehicle this PC is: host name against profile")
    e = identity.expected_profile
    check("a vehicle host names its profile",
          [e("gvipc-evo-01"), e("gvipc-evo-02"), e("GVIPC-EVO-2"), e("gvipc-evo-12")]
          == ["agv-01", "agv-02", "agv-02", "agv-12"])
    check("any other host is no vehicle and is not checked",
          [e("devbox"), e("gvipc-evo-01x"), e("gvipc-ce"), e(""), e(None)] == [None] * 5)
    why = identity.check("gvipc-evo-02", "agv-01")
    check("unit 2 running agv-01 is refused, naming the fix",
          why is not None and "agv-02" in why and "vehicle.env" in why, why)
    check("a matching host and profile pass, a dev box passes",
          identity.check("gvipc-evo-02", "agv-02") is None and identity.check("laptop", "agv-02") is None)


def _selector(content, env_profile=None):
    """AGV_PROFILE after sourcing vehicle.sh with this vehicle.env (None: no file), and stderr."""
    with tempfile.TemporaryDirectory() as d:
        if content is not None:
            with open(os.path.join(d, "vehicle.env"), "w") as fh:
                fh.write(content)
        env = {k: v for k, v in os.environ.items() if k != "AGV_PROFILE"}
        env["AMR_STATE_DIR"] = d
        if env_profile:
            env["AGV_PROFILE"] = env_profile
        script = f'set -euo pipefail; source "{ROOT}/amr_ws/env/vehicle.sh"; echo "${{AGV_PROFILE:-}}"'
        r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=True)
        return r.stdout.strip(), r.stderr


def test_selector():
    print("\nthe local selector: $AMR_STATE_DIR/vehicle.env")
    check("no file: the default profile", _selector(None) == ("", ""))
    check("one line selects the profile", _selector("AGV_PROFILE=agv-02\n")[0] == "agv-02")
    check("comments and spaces are fine", _selector("# unit 2\n  AGV_PROFILE=agv-02  \n")[0] == "agv-02")
    out, err = _selector("AGV_PROFILE=agv-02; touch /tmp/x\n")
    check("anything but a plain name is not read, and says so", out == "" and "vehicle.env" in err,
          (out, err))
    check("a quoted value is not a plain name", _selector('AGV_PROFILE="agv-02"\n')[0] == "")
    check("an AGV_PROFILE already in the environment wins",
          _selector("AGV_PROFILE=agv-02\n", env_profile="agv-01")[0] == "agv-01")


def test_suite_pins_the_reference_profile():
    print("\nthe tests run against agv-01 on either PC")
    check("run_all.py pins AGV_PROFILE=agv-01", os.environ.get("AGV_PROFILE") == "agv-01",
          os.environ.get("AGV_PROFILE"))
    loose = []
    for d in sorted(glob.glob(os.path.join(ROOT, "amr_ws", "src", "*", "test"))):
        path = os.path.join(d, "conftest.py")
        text = open(path).read() if os.path.exists(path) else ""
        if 'os.environ["AGV_PROFILE"] = "agv-01"' not in text:
            loose.append(os.path.relpath(d, ROOT))
    check("every amr_ws test directory's conftest.py pins it", not loose, loose)
    with open(os.path.join(ROOT, "profiles", "agv-02.json")) as fh:
        two = json.load(fh)
    check("agv-02 is not a station vehicle until it is taught (station and live off)",
          not two["station"]["enabled"] and not two["tape_loc"]["live"])


TESTS = [test_every_profile, test_identity, test_selector, test_suite_pins_the_reference_profile]
