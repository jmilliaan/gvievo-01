#!/usr/bin/env python3
"""One AUTO run's bag -> CSVs and a timeline report (tools/run_log.sh calls it).

    python3 tools/bag_report.py ~/.amr/runs/<stamp>        (needs amr_ws sourced)

Writes <run>/csv/*.csv and prints the timeline: run states, steps and holds,
localization states, field warnings, mux source changes, drive power, panel
edges, DO changes, events and rosout warnings. Then, per step of the run
(/amr/run_state step changes): duration, distance, mean and max speed and peak
cross-track error.
Time is seconds from the first recorded message (bag receive time).
"""
import csv
import math
import os
import sys

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from agv_core import config  # noqa: E402

RUN_STATES = {0: "IDLE", 1: "READY", 2: "EXECUTING", 3: "PAUSED", 4: "BLOCKED", 5: "FAULT", 6: "DONE"}
LOC_STATES = {0: "UNLOCALIZED", 1: "CHECKING", 2: "READY", 3: "LOST"}
MUX_SOURCES = {0: "none", 1: "teleop", 2: "follow", 3: "rotate", 4: "manual", 5: "commissioning",
               6: "pendant"}


def read_bag(path):
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=path, storage_id="mcap"),
                rosbag2_py.ConverterOptions("cdr", "cdr"))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    out = {}
    while reader.has_next():
        topic, data, t_ns = reader.read_next()
        try:
            msg = deserialize_message(data, get_message(types[topic]))
        except Exception:  # noqa: BLE001 - an unknown type is skipped, not fatal
            continue
        out.setdefault(topic, []).append((t_ns * 1e-9, msg))
    return out


def write_csv(d, name, header, rows):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main(run):
    bag = read_bag(os.path.join(run, "bag"))
    if not bag:
        print("empty bag")
        return
    t0 = min(v[0][0] for v in bag.values())
    csvd = os.path.join(run, "csv")
    r = config.WHEEL_DIA_M / 2.0
    timeline = []

    def ev(t, what):
        timeline.append((t - t0, what))

    # -- wheels: body speed, yaw rate, distance, heading by the encoders ---------------
    wheels, dist, yaw = [], 0.0, 0.0
    prev = None
    for t, m in bag.get("/wheel_states", []):
        v = r * (m.left_vel_rad_s + m.right_vel_rad_s) / 2.0
        w = r * (m.right_vel_rad_s - m.left_vel_rad_s) / config.TRACK_M
        if prev is not None and m.left_valid and m.right_valid:
            dl = (m.left_pos_rad - prev.left_pos_rad) * r
            dr = (m.right_pos_rad - prev.right_pos_rad) * r
            dist += abs(dl + dr) / 2.0
            yaw += (dr - dl) / config.TRACK_M
        prev = m
        wheels.append((t - t0, v, w, dist, math.degrees(yaw), m.left_counts, m.right_counts,
                       m.left_valid and m.right_valid))
    write_csv(csvd, "wheels.csv", ["t", "v_mps", "yaw_rate_rad_s", "dist_m", "yaw_enc_deg",
                                   "left_counts", "right_counts", "valid"], wheels)

    def at(series, t, col):
        """Value of series[col] at time t (series rows start with relative t)."""
        lo, hi = 0, len(series) - 1
        if hi < 0:
            return None
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if series[mid][0] <= t:
                lo = mid
            else:
                hi = mid - 1
        return series[lo][col]

    # -- gyro --------------------------------------------------------------------------
    imu, gyaw = [], 0.0
    last = None
    for t, m in bag.get("/imu/data", []):
        if last is not None:
            gyaw += m.angular_velocity.z * (t - last)
        last = t
        imu.append((t - t0, m.angular_velocity.z, math.degrees(gyaw)))
    write_csv(csvd, "imu.csv", ["t", "yaw_rate_rad_s", "yaw_gyro_deg"], imu)

    # -- commands ----------------------------------------------------------------------
    write_csv(csvd, "cmd_wheel_vel.csv", ["t", "left_rad_s", "right_rad_s"],
              [(t - t0, m.left_rad_s, m.right_rad_s) for t, m in bag.get("/cmd_wheel_vel", [])])

    # -- run state ---------------------------------------------------------------------
    fields = ["state", "run_id", "mission_id", "route_id", "step_index", "step_id", "step_type",
              "step_v_mps", "cross_track_m", "hold_cause", "fault_code", "drive_power", "premove",
              "reason"]
    rows, was = [], {}
    for t, m in bag.get("/amr/run_state", []):
        row = {f: getattr(m, f, "") for f in fields}
        row["state"] = RUN_STATES.get(m.state, m.state)
        rows.append([t - t0] + [row[f] for f in fields])
        for f, label in (("state", "run"), ("step_id", "step"), ("hold_cause", "hold"),
                         ("drive_power", "drive power"), ("premove", "pre-move")):
            if row[f] != was.get(f):
                if (f in was or row[f]) and (f != "hold_cause" or row[f]):
                    ev(t, f"{label}: {row[f]!s}" + (f"  ({row['reason']})" if f == "state" else ""))
        was = row
    write_csv(csvd, "run_state.csv", ["t"] + fields, rows)

    # -- localization state ------------------------------------------------------------
    loc_fields = ["state", "operator_confirmed", "can_confirm", "cov_xx", "cov_yy", "cov_yaw",
                  "scan_match", "last_jump_m", "code", "reason"]
    loc, was = [], None
    for t, m in bag.get("/amr/localization_state", []):
        row = {f: getattr(m, f, "") for f in loc_fields}
        row["state"] = LOC_STATES.get(m.state, m.state)
        loc.append([t - t0] + [row[f] for f in loc_fields])
        if row["state"] != was:
            ev(t, f"localization: {row['state']}" + (f"  ({row['reason']})" if row["reason"] else ""))
            was = row["state"]
    write_csv(csvd, "localization_state.csv", ["t"] + loc_fields, loc)

    # -- mux, drives, panel, I/O -------------------------------------------------------
    mux, was = [], None
    for t, m in bag.get("/amr/mux_state", []):
        src = MUX_SOURCES.get(m.source, m.source)
        mux.append((t - t0, src, int(m.inhibited), m.warning_level, m.speed_scale, int(m.protective_clear),
                    m.code, m.reason))
        key = (src, m.warning_level, int(m.protective_clear))
        if key != was:
            ev(t, f"mux: source {src}, warning level {m.warning_level}, protective "
                  f"{'clear' if m.protective_clear else 'VIOLATED'}, scale {m.speed_scale:.2f}")
            was = key
    write_csv(csvd, "mux.csv", ["t", "source", "inhibited", "warning_level", "speed_scale",
                                "protective_clear", "code", "reason"], mux)
    drv, was = [], None
    for t, m in bag.get("/drives/status", []):
        link, pw, why = getattr(m, "link_state", ""), getattr(m, "power_wanted", None), \
            getattr(m, "power_reason", "")
        drv.append((t - t0, int(m.operational), link, pw, why, m.left_state, m.right_state,
                    hex(m.left_error_code), hex(m.right_error_code)))
        key = (m.operational, link, pw)
        if key != was:
            ev(t, f"drives: operational={m.operational} link={link} power_wanted={pw} ({why})")
            was = key
    write_csv(csvd, "drives.csv", ["t", "operational", "link_state", "power_wanted", "power_reason",
                                   "left_state", "right_state", "left_err", "right_err"], drv)
    for t, m in bag.get("/amr/panel_state", []):
        if m.start_edge:
            ev(t, "PANEL Start")
        if m.reset_edge:
            ev(t, "PANEL Reset")
    io, was = [], None
    for t, m in bag.get("/amr/io", []):
        idx = [str(i) for i, b in enumerate(m.do_requested) if b]
        io.append((t - t0, " ".join(idx), " ".join(str(i) for i, b in enumerate(m.di) if b)))
        if idx != was:
            ev(t, f"DO on: {', '.join(f'DO{int(i):02d}' for i in idx) or 'none'}")
            was = idx
    write_csv(csvd, "io.csv", ["t", "do_on", "di_on"], io)
    for t, m in bag.get("/amr/events", []):
        ev(t, f"event [{m.source}] {m.code}: {m.text}")
    for t, m in bag.get("/rosout", []):
        if m.level >= 30:  # WARN and above
            ev(t, f"rosout {m.name}: {m.msg[:160]}")

    # -- report ------------------------------------------------------------------------
    print(f"run {run}")
    print(f"  {(max(v[-1][0] for v in bag.values()) - t0):.1f} s recorded, "
          f"{', '.join(f'{k} {len(v)}' for k, v in sorted(bag.items()))}")
    print("\nTIMELINE")
    for t, what in sorted(timeline):
        print(f"  {t:8.2f}  {what}")


    # Steps: consecutive run_state rows with the same (state, step_id).
    print("\nSTEPS (EXECUTING)")
    segs, cur = [], None
    ix_step, ix_xt = fields.index("step_id") + 1, fields.index("cross_track_m") + 1
    for row in rows:
        key = (row[1], row[ix_step])
        if cur is None or key != cur[0]:
            if cur:
                segs.append((cur[0], cur[1], row[0]))
            cur = (key, row[0])
    if cur:
        segs.append((cur[0], cur[1], wheels[-1][0] if wheels else cur[1]))
    for (state, step), a, b in segs:
        if state != "EXECUTING" or b - a < 0.2:
            continue
        sp = [row[1] for row in wheels if a <= row[0] < b]
        xt = [row[ix_xt] for row in rows if a <= row[0] < b]
        d0, d1 = at(wheels, a, 3), at(wheels, b, 3)
        line = f"  {a:8.2f}-{b:8.2f}  {step or '-':12s} {b - a:6.1f} s"
        if d0 is not None and d1 is not None:
            line += f"  {d1 - d0:6.2f} m"
        if sp:
            line += f"  v mean {sum(sp) / len(sp):5.2f} max {max(sp):5.2f} m/s"
        if xt:
            line += f"  cross-track max {max(xt, key=abs):+.3f} m"
        print(line)


if __name__ == "__main__":
    main(os.path.expanduser(sys.argv[1]) if len(sys.argv) > 1 else ".")
