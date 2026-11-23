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


# The wiring source of truth (documentation/electrical/01-schematic/io-mapping.md, read only:
# the electrical docs change through their own SKILL workflow, never from here).
IO_MAPPING = os.path.join(ROOT, "documentation", "electrical", "01-schematic", "io-mapping.md")
# Known gaps between the sheet and the profiles, as exact sets (unified plan WP-Y2, 2026-11-16).
# A test fails when one closes too, so the entry is removed deliberately.
KNOWN_OPEN_DO = set()                   # gvievo-ce: only DO0 / DO1 are switched
KNOWN_PLACEHOLDER_ROWS = set()          # gvievo-ce: section 4 is the kyb unit, no «TB?» rows


def _io_table(text, heading):
    """{channel: description} of the pipe table under `heading` in io-mapping.md section 4,
    ranges (DO2–DO7, DI0A–DI0F) expanded to one entry per channel. None: no such table."""
    import re
    sec = text.split("\n## 4.", 1)
    if len(sec) < 2:
        return None
    body = sec[1].split("\n## ", 1)[0]
    part = body.split(f"\n### {heading}\n", 1)
    if len(part) < 2:
        return None
    rows = {}
    for line in part[1].split("\n### ", 1)[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) < 2:
            continue
        m = re.fullmatch(r"(DI|DO)([0-9A-F]{1,2})(?:\s*[–-]\s*(?:DI|DO)([0-9A-F]{1,2}))?", cells[0])
        if not m:
            continue
        lo = int(m.group(2), 16)
        hi = int(m.group(3), 16) if m.group(3) else lo
        for ch in range(lo, hi + 1):
            rows[ch] = " | ".join(cells[1:])
    return rows or None


def _unwired(desc):
    d = desc.lower()
    return "not used" in d or "not wired" in d or "spare" in d or "not connected" in d


def test_wiring():
    """Profile DI/DO map against io-mapping.md (S-io-mapping-parsed-profile-test, unified plan
    WP-Y2): drift between the sheet and either profile, not between the sheet and the copper."""
    import re
    print("\nthe profiles' I/O map against io-mapping.md")
    text = open(IO_MAPPING, encoding="utf-8").read()
    di, do = _io_table(text, "Digital inputs"), _io_table(text, "Digital outputs")
    check("io-mapping.md section 4 has the digital input and output tables", di and do,
          "" if di and do else "table not found: io-mapping.md section 4 was reworded; update this test")
    di, do = di or {}, do or {}
    head = re.search(r"\n## 4\.[^\n]*?(\d+) DI / (\d+) DO", text)
    n_di, n_do = (int(head.group(1)), int(head.group(2))) if head else (0, 0)
    profiles = {}
    # gvievo-ce: io-mapping.md section 4 is this branch's unit (agv-01, the kyb vehicle) only;
    # agv-02 is the gvievo-main unit's wiring and is not checked against it here.
    for path in [os.path.join(config.PROFILE_DIR, "agv-01.json")]:
        with open(path) as fh:
            profiles[os.path.splitext(os.path.basename(path))[0]] = json.load(fh)

    # Panel and pendant channels land on the rows that name their device.
    want = {("panel", "di_start"): "START", ("panel", "di_reset"): "RESET",
            ("panel", "di_auto"): "MANUAL/AUTO",
            ("pendant", "di_fwd"): "FORWARD", ("pendant", "di_rvs"): "REVERSE",
            ("pendant", "di_left"): "LEFT", ("pendant", "di_right"): "RIGHT",
            ("panel", "di_estop"): "ESTOP"}   # emergency-suite Part B E1 (the sheet's row name)
    bad = [f"{n}: {s}.{k}={p[s][k]} -> {di.get(p[s][k])!r}" for n, p in profiles.items()
           for (s, k), word in want.items() if k in p[s] and word not in (di.get(p[s][k]) or "")]
    check("every panel and pendant channel is the DI the sheet names for it", not bad, bad)
    com1 = [f"{n}: {k}={p['panel'][k]}" for n, p in profiles.items() for k in ("di_estop",)
            if k in p["panel"] and not (8 <= p["panel"][k] <= 15 and "COM1" in di.get(p["panel"][k], ""))]
    check("the E-stop signal reads in the COM1 group DI08-DI0F", not com1, com1)

    # Names: a wired channel is named, an unwired one is not.
    names = []
    for n, p in profiles.items():
        for kind, rows, key in (("DI", di, "di_names"), ("DO", do, "do_names")):
            for ch, desc in sorted(rows.items()):
                name = p["dio"][key][ch] if ch < len(p["dio"][key]) else None
                if _unwired(desc) == (name not in ("[SPARE]", "n/c")):
                    names.append(f"{n}: {kind}{ch:X} {name!r} vs {desc[:30]!r}")
    check("a wired channel has a name, an unused one is [SPARE] or n/c (DI09 ESTOP, DO0/DO1 horn)",
          not names, names)
    horn = [f"{n}: {p['dio']['do_names'][:2]}" for n, p in profiles.items()
            if not all("Horn" in x for x in p["dio"]["do_names"][:2])]
    check("DO0 and DO1 are named as the horn's two sounds", not horn and "horn" in do.get(0, "").lower()
          and "horn" in do.get(1, "").lower(), horn)

    # Outputs the software switches are wired, except the known DO8.
    switched = set()
    for p in profiles.values():
        d = p["dio"]
        switched |= {(k, ch) for k in ("motion_on", "alarm_on", "movement_horn") for ch in d[k]}
        # (horn.do_channel went with the horn section, lean plan D16, 2026-11-16)
    open_do = {(k, ch) for k, ch in switched if _unwired(do.get(ch, "not wired"))}
    check("every switched DO is a wired one (gvievo-ce: DO0 movement, DO1 alarm)",
          open_do == KNOWN_OPEN_DO, sorted(open_do))
    counts = [f"{n}: {p['dio']['num_di']}/{p['dio']['num_do']}" for n, p in profiles.items()
              if not (p["dio"]["num_di"] <= n_di and p["dio"]["num_do"] <= n_do)]
    check("num_di / num_do fit the module the sheet names (CK-TP5162, 16 DI / 16 DO)",
          n_di and not counts, counts or f"header {n_di}/{n_do}")
    held = {f"DI{ch:02X}" for ch, desc in di.items() if "«" in desc} | \
           {f"DO{ch}" for ch, desc in do.items() if "«" in desc}
    check("the sheet's open placeholders are exactly KNOWN_PLACEHOLDER_ROWS (none on gvievo-ce)",
          held == KNOWN_PLACEHOLDER_ROWS, sorted(held))


TESTS = [test_every_profile, test_identity, test_selector, test_suite_pins_the_reference_profile, test_wiring]
