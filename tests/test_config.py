"""The vehicle profile: loading, validation, and the derived constants."""
import math
import os
import pathlib
import struct
import sys
import threading

from helpers import FAIL, ROOT, check, sensor

import autopilot
import config
import kinematics
import motion


def rows_by_path(sections):
    """describe() rows addressed by their JSON path, not by where they display.

    describe() gathers the speed keys out of three sections into one at the top
    of the page, so a row's SECTION is a presentation choice while its path is
    the fact. Keying on the path lets these tests assert what they actually mean
    - this value reaches the page, with its note attached - without pinning the
    layout, which is free to change again.

    A gathered row already carries its full path; a row shown in its own section
    carries a bare key and gets the section prefixed back on.

    The tree marker on a nested row is stripped first. It says the row sits
    UNDER the rule slot above it - branch_default belongs with the junction
    rules it governs - and that is layout, not part of the path.
    """
    out = {}
    for s in sections:
        for r in s["rows"]:
            key = r["key"].lstrip("\u2514 ")
            out[key if key.split(".")[0] in config._SCHEMA
                else f"{s['name']}.{r['key']}"] = r
    return out


def test_config_profile():
    """The profile is the whole tuning surface, so a bad one must be refused
    loudly at boot rather than showing up as odd behaviour on a length of tape."""
    import copy
    import json
    import shutil
    import tempfile
    print("\nvehicle profile loading")

    base = json.load(open(config.profile_path()))

    def load_with(mutate, name="agv-01"):
        d = copy.deepcopy(base)
        mutate(d)
        # Written under its profile NAME, not a random temp name: the loader
        # requires profile_name to match the filename, so a tmpXXXX.json would
        # be refused for the wrong reason and every check below would pass
        # vacuously.
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, f"{name}.json")
        with open(path, "w") as fh:
            json.dump(d, fh)
        try:
            config.load(path)
            return None
        except config.ConfigError as e:
            return str(e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            config.load()          # always restore the real profile

    def refuses(name, mutate, expect=""):
        msg = load_with(mutate)
        check(name, msg is not None and expect in (msg or ""), msg or "accepted!")

    check("the real profile loads", config.PROFILE_NAME == "agv-01",
          config.PROFILE_NAME)
    refuses("a typo'd key is refused",
            lambda d: d["autopilot"].update({"k_rato": d["autopilot"].pop("k_ratio")}),
            "unknown key")
    refuses("a missing key is refused",
            lambda d: d["autopilot"].pop("kd"), "missing key")
    refuses("an unknown section is refused",
            lambda d: d.update({"extra": {}}), "unknown top-level")
    refuses("a negative gain is refused, by name",
            lambda d: d["autopilot"].update(k_ratio=-1.0), "K_RATIO")
    refuses("auto_rpm above the motor limit is refused",
            lambda d: d["autopilot"].update(auto_rpm=9000.0), "AUTO_RPM")
    refuses("a bool where a number belongs is refused",
            lambda d: d["autopilot"].update(kd=True), "expected a number")
    refuses("duplicate CAN node IDs are refused",
            lambda d: d["can"].update(sensor_node=2), "distinct")
    # The pairing neither module could check alone before config existed.
    # Read 6083h out of the doc rather than hardcoding it. This used to say
    # 2000.0, which stopped testing anything the day the driver ramp was raised
    # to 2400 - the value was still refused-looking but was legitimately below
    # the new limit, so the check passed for the wrong reason.
    refuses("a software ramp at or above 6083h is refused",
            lambda d: d["autopilot"].update(
                ramp_accel_rpm_s=float(d["drivers"]["ramp"]["auto"]["accel"])),
            "must stay below")
    # A profile written before the units changed must not run silently on a
    # stale key - the loader rejects unknowns, which is what catches it.
    refuses("a pre-rename profile (line_loss_grace_s) is refused",
            lambda d: d["autopilot"].update(
                line_loss_grace_s=d["autopilot"].pop("line_loss_grace_m")),
            "unknown key")
    refuses("a pre-rename profile (sr_pos_coef) is refused",
            lambda d: d["autopilot"].update(
                sr_pos_coef=d["autopilot"].pop("sr_pos_frac")),
            "unknown key")

    refuses("a driver timeout inside the telemetry period is refused",
            lambda d: d["timing"].update(driver_timeout_s=0.1),
            "driver_timeout_s")
    refuses("an empty can.channel is refused",
            lambda d: d["can"].update(channel=""), "can.channel")

    # The standing branch default is a string from a closed set, and a typo in
    # it steers the vehicle: an unrecognised value that fell through to STRAIGHT
    # would silently stop taking the U-turn.
    refuses("a spin_ratio above 1 is refused",
            lambda d: d["manual"].update(spin_ratio=1.5), "spin_ratio")
    refuses("a zero spin_ratio is refused",
            lambda d: d["manual"].update(spin_ratio=0.0), "spin_ratio")
    # Rounding, not the fraction, is what makes this dead: 0.001 is a legal
    # fraction that still commands 0 r/min against a small full_rpm.
    refuses("a spin_ratio that rounds to 0 r/min is refused",
            lambda d: d["manual"].update(full_rpm=100, spin_ratio=0.001),
            "rounds to 0")

    # The resume window: a missing key is as fatal as an unknown one, and the
    # ceiling is what catches a value typed in milliseconds - which would
    # switch the stations off for the rest of the run without a symptom.
    refuses("a station row missing direction is refused",
            lambda d: d["stop_until_start_button"][0].pop("direction"), "direction")
    refuses("an unknown stop direction is refused",
            lambda d: d["stop_until_start_button"][0].update(direction="forward"), "direction")
    refuses("obsolete global ignore_t is refused",
            lambda d: d["stop_until_start_button"][0].update(ignore_t=20), "expected exactly")

    refuses("an unknown branch_default is refused",
            lambda d: d["autopilot"].update(branch_default="rightmost"),
            "branch_default")
    refuses("a capitalised branch_default is refused rather than folded",
            lambda d: d["autopilot"].update(branch_default="Right"),
            "branch_default")

    # The horn is the only output this software energises, and both ways of
    # getting it wrong are silent: a channel off the end of the module writes
    # nothing, and a horn enabled without the DIO scan has nobody to write it.
    # Neither shows up as an error at run time - both show up as a vehicle that
    # drives off without sounding.
    refuses("a horn channel past the end of the module is refused",
            lambda d: d["horn"].update(do_channel=d["dio"]["num_do"]),
            "horn.do_channel")
    refuses("a negative horn channel is refused",
            lambda d: d["horn"].update(do_channel=-1), "horn.do_channel")
    refuses("a horn without the DIO scan that writes it is refused",
            lambda d: (d["dio"].update(enabled=False),
                       d["panel"].update(enabled=False)),
            "horn.enabled")

    # The name in the file must match the file. A profile copied for a second
    # vehicle and not renamed would report the old identity in the event log
    # and in every run CSV header.
    msg = load_with(lambda d: None, name="agv-99")
    check("profile_name must match the filename", msg is not None
          and "agv-99" in (msg or ""), msg or "accepted!")

    # -- which vehicle this process is --------------------------------------
    check("the default profile resolves into profiles/",
          config.profile_path().endswith(os.path.join("profiles", "agv-01.json")),
          config.profile_path())
    os.environ[config.PROFILE_ENV_VAR] = "agv-02"
    try:
        check("AGV_PROFILE selects the profile",
              config.profile_path().endswith("agv-02.json"),
              config.profile_path())
        check("an explicit path still wins over the env var",
              config.profile_path("agv-03").endswith("agv-03.json"))
        try:
            config.load()
            check("a missing profile is fatal", False, "accepted!")
        except config.ConfigError as e:
            check("a missing profile names the env var and what exists",
                  config.PROFILE_ENV_VAR in str(e) and "agv-01" in str(e),
                  str(e)[:80])
    finally:
        del os.environ[config.PROFILE_ENV_VAR]
        config.load()

    # A rejected profile must leave the live one untouched - this is what makes
    # load() safe to call again later from a reload endpoint.
    load_with(lambda d: d["autopilot"].update(k_ratio=-1.0))
    check("a rejected profile leaves the live one intact",
          config.K_RATIO == 11.3, f"K_RATIO={config.K_RATIO}")


def test_derived_constants():
    """Values that used to be literals in .py files are now computed from the
    profile primitives.

    The geometry constants are checked against their former literals, because
    those come from a tape measure and must not drift. Everything else is
    checked as a RELATIONSHIP to its inputs - asserting a tuned number here
    would just break the suite every time someone edits the profile, which is
    the whole point of the profile existing."""
    print("\nderived constants follow their inputs")
    close = lambda a, b: abs(a - b) < abs(b) * 1e-6
    check("MPS_PER_RPM", close(config.MPS_PER_RPM, 3.14159265e-4),
          f"{config.MPS_PER_RPM:.6e}")
    check("RPM_PER_MPS", close(config.RPM_PER_MPS, 3183.0989),
          f"{config.RPM_PER_MPS:.4f}")
    check("RAD_S_PER_RPM_DIFF", close(config.RAD_S_PER_RPM_DIFF, 6.4641824e-4),
          f"{config.RAD_S_PER_RPM_DIFF:.6e}")
    check("MAX_SPEED_MPS", close(config.MAX_SPEED_MPS, 1.2566371),
          f"{config.MAX_SPEED_MPS:.4f}")
    check("MANUAL_HALF_RPM is full_rpm * half_ratio, rounded",
          config.MANUAL_HALF_RPM
          == round(config.MANUAL_FULL_RPM * config.MANUAL_HALF_RATIO),
          f"{config.MANUAL_FULL_RPM} x {config.MANUAL_HALF_RATIO} "
          f"-> {config.MANUAL_HALF_RPM}")
    check("MANUAL_SPIN_RPM is full_rpm * spin_ratio, rounded",
          config.MANUAL_SPIN_RPM
          == round(config.MANUAL_FULL_RPM * config.MANUAL_SPIN_RATIO),
          f"{config.MANUAL_FULL_RPM} x {config.MANUAL_SPIN_RATIO} "
          f"-> {config.MANUAL_SPIN_RPM}")
    check("DT band is 0.2x .. 5x nominal",
          close(config.DT_MIN_S, 0.2 * config.DT_NOMINAL_S)
          and close(config.DT_MAX_S, 5.0 * config.DT_NOMINAL_S),
          f"{config.DT_MIN_S} .. {config.DT_MAX_S}")
    check("ACCEL/DECEL track the auto ramp block",
          config.ACCEL_RPM_S == config.RAMP["auto"]["accel"]
          and config.DECEL_RPM_S == config.RAMP["auto"]["decel"],
          f"{config.ACCEL_RPM_S} / {config.DECEL_RPM_S}")
    check("TPDO1_COB is 0x180 + sensor node",
          config.TPDO1_COB == 0x180 + config.SENSOR_NODE, hex(config.TPDO1_COB))
    check("NODES maps the configured driver IDs",
          config.NODES == {config.LEFT: "left", config.RIGHT: "right"},
          str(config.NODES))
    # motion's table is built from the profile now, not from module literals.
    full, half = config.MANUAL_FULL_RPM, config.MANUAL_HALF_RPM
    spin = config.MANUAL_SPIN_RPM
    check("manual jog table is built from the profile",
          motion.velocities("forward_left") == (half, full)
          and motion.velocities("forward") == (full, full)
          and motion.velocities("stop") == (0, 0),
          f"fwd-left {motion.velocities('forward_left')}")

    # A spin takes spin_ratio, NOT half_ratio. These shared one number until
    # now, and sharing it tied the turn radius of a curve to the yaw rate of a
    # spin - so raising full_rpm for open-floor travel sped up the manoeuvre
    # done in a confined space. Asserted per-direction because the pad has two
    # spin buttons and only one of them being converted is a live hazard that
    # the aggregate would hide.
    check("*** a spin takes spin_ratio, not the curve's half_ratio ***",
          motion.velocities("left") == (-spin, spin)
          and motion.velocities("right") == (spin, -spin),
          f"left {motion.velocities('left')} right {motion.velocities('right')}")
    check("...both wheels equal and opposite, so it turns on its axis and "
          "travels nowhere",
          sum(motion.velocities("left")) == 0
          and sum(motion.velocities("right")) == 0)
    check("...and the two spins are mirror images",
          motion.velocities("left") == tuple(
              -v for v in motion.velocities("right")))
    check("the curves are untouched by the spin speed - they still take the "
          "inner wheel to half and leave the outer at full",
          {motion.velocities(d) for d in ("forward_left", "forward_right",
                                          "reverse_left", "reverse_right")}
          == {(half, full), (full, half), (-half, -full), (-full, -half)})
    check("a spin commands something - a ratio that rounded to zero would be "
          "a dead button, and _validate() refuses it",
          spin > 0, f"{spin} r/min")


def test_params_view():
    """describe() is what /params renders, and it is generated from _SCHEMA.

    The failure this guards is silent and specific to a display page: a
    parameter the vehicle is running on that nobody can see. A hand-written
    page drifts the moment a key is added - so the page is generated, and this
    checks the generator covers the schema rather than checking a list.
    """
    print("\nthe parameters view covers the whole profile")

    sections = config.describe()
    rows = rows_by_path(sections)

    missing = [f"{sec}.{key}" for sec, fields in config._SCHEMA.items()
               for key in fields if f"{sec}.{key}" not in rows]
    check("every schema key is displayed", not missing, str(missing))

    # The three the flat schema cannot express, and the one top-level list.
    for sec, key in (("drivers", "ramp.auto.accel"), ("dio", "di_names"),
                     ("lidar", "zone_bytes")):
        check(f"the nested {sec}.{key} is displayed", f"{sec}.{key}" in rows)
    # The junction table moved into the "rfid rules" block, grouped with every
    # other kind of thing a tag can mean rather than standing on its own.
    rules = next((s for s in sections if s["name"] == "rfid rules"), None)
    check("the junction table is displayed under the RFID rules",
          rules is not None
          and any("branch latch" in r["key"] for r in rules["rows"]))

    derived = {r["key"] for s in sections if s["name"] == "derived"
               for r in s["rows"]}
    for const in ("MPS_PER_RPM", "MAX_SPEED_MPS", "MANUAL_HALF_RPM",
                  "MANUAL_SPIN_RPM",
                  "LINE_LOSS_GRACE_MAX_S", "TPDO1_COB"):
        check(f"{const} is shown as derived", const in derived)
    # Derived values cannot be edited, so they must not be offered as if they
    # could: no JSON key, and the relation that produced them instead.
    check("a derived row names its relation, not a JSON key",
          all(r.get("from") and not r["const"]
              for s in sections if s["name"] == "derived" for r in s["rows"]))

    check("the profile's own values are shown",
          rows["autopilot.k_ratio"]["value"] == config._fmt(config.K_RATIO)
          and rows["can.channel"]["value"] == config.CAN_CHANNEL,
          rows["autopilot.k_ratio"]["value"])

    # Units are read off the exported name's suffix. The ones worth pinning are
    # the ones a naive suffix rule gets wrong.
    units = {r["const"]: r["unit"] for s in sections for r in s["rows"]}
    units.update({r["key"]: r["unit"] for s in sections
                  if s["name"] == "derived" for r in s["rows"]})
    for const, want in (("LOOP_PERIOD_S", "s"), ("CAN_HEARTBEAT_MS", "ms"),
                        ("TI_DEADBAND_MM", "mm"), ("TRACK_M", "m"),
                        ("RAMP_JERK_RPM_S2", "r/min/s\u00b2"),
                        ("MON_DRV_WARN_C", "\u00b0C"),
                        ("MON_BUS_V_WARN_LOW", "V"),
                        ("MPS_PER_RPM", "m/s per r/min")):
        check(f"{const} reads as {want}", units.get(const) == want,
              repr(units.get(const)))

    # true/false, not Python's True/False - the page is read next to the JSON
    # file it describes, and the two must be the same word.
    check("booleans render as JSON does",
          rows["autopilot.dry_run"]["value"] in ("true", "false"),
          rows["autopilot.dry_run"]["value"])
    check("a whole float drops its .0",
          rows["vehicle.motor_max_rpm"]["value"] == "4000",
          rows["vehicle.motor_max_rpm"]["value"])
    # An empty string is a SETTING here (rfid.init_hex empty means the reader is
    # never told to start), so it must never render as a blank cell.
    check("no cell is blank", all(r["value"] for s in sections
                                  for r in s["rows"]))


def test_tuning_notes_are_parsed_not_restated():
    """The prose on /params is config.py's own docstring, parsed out of it.

    Every setting that is not self-evident is already explained at the top of
    this module - it is written there BECAUSE JSON cannot carry comments.
    Copying those paragraphs into a template makes two versions of one
    explanation, and the one that goes stale is the one on the screen.
    """
    print("\ntuning notes are parsed from the module docstring")

    notes = config.tuning_notes()
    check("the notes parse at all", len(notes) > 20, f"{len(notes)} note(s)")
    check("no note is empty", all(v.strip() for v in notes.values()))

    # A heading naming several keys has to reach all of them, or the second and
    # third key look undocumented while their paragraph exists.
    for key in ("autopilot.k_ratio", "autopilot.kd", "autopilot.ki"):
        check(f"{key} carries the shared gains note", key in notes)
    check("a key named without its section still resolves",
          "vehicle.invert_right" in notes)
    check("a section-wide note is kept as such", "rfid.*" in notes)

    # Attachment, not just parsing: the note has to land on the row.
    rows = rows_by_path(config.describe())
    check("the dry-run note reaches its row",
          "dry run" in (rows["autopilot.dry_run"]["note"] or "").lower())
    check("a nested ramp row inherits the drivers.ramp note",
          "6083h" in (rows["drivers.ramp.auto.accel"]["note"] or ""))
    check("a section note reaches a row that has none of its own",
          "CF821" in (rows["rfid.ip"]["note"] or ""))

    # Parsing must never be able to take the page down: a docstring rewritten
    # into prose yields no notes, not an exception.
    doc, config.__doc__ = config.__doc__, "no headings here at all"
    try:
        check("a docstring with no notes yields none, quietly",
              config.tuning_notes() == {})
    finally:
        config.__doc__ = doc
    check("...and the notes come back", len(config.tuning_notes()) > 20)


TESTS = [
    test_config_profile,
    test_derived_constants,
    test_params_view,
    test_tuning_notes_are_parsed_not_restated,
]
