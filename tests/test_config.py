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
    refuses("a software ramp at or above 6083h is refused",
            lambda d: d["autopilot"].update(ramp_accel_rpm_s=2000.0),
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
    check("manual jog table is built from the profile",
          motion.velocities("forward_left") == (half, full)
          and motion.velocities("forward") == (full, full)
          and motion.velocities("stop") == (0, 0),
          f"fwd-left {motion.velocities('forward_left')}")


TESTS = [
    test_config_profile,
    test_derived_constants,
]
