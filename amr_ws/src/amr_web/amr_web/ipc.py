"""The IPC's own health for the header chip: CPU temperature and thermal throttling.

Pure sysfs readers with an injectable root (no rclpy), so a fake tree tests them.
The web runs on the PC it reports, so these are read here, not carried in a message.

Throttling (WP-P11, S-`ipc-throttle-telemetry`, 2026-11-16): the N97 throttles while it
shows ~65 deg C (4200 package events in ~3 h, 2026-10). cpu0's package counters are the
package's (every CPU shows the same package count); the per-core ones are not read.
A throttle event is TM1/TM2 clock modulation, not a halt. Report only: no warn level
until a threshold is a profile key.
"""

from __future__ import annotations

import os

CPU_ROOT = "/sys/devices/system/cpu"
CLASS_ROOT = "/sys/class"


def read_ipc_temp(root: str = CLASS_ROOT) -> dict | None:
    """The IPC's CPU temperature from the coretemp hwmon (package, hottest core), deg C.

    Falls back to the x86_pkg_temp thermal zone. None when neither exists (a VM).
    """
    try:
        for h in sorted(os.listdir(os.path.join(root, "hwmon"))):
            d = os.path.join(root, "hwmon", h)
            try:
                with open(os.path.join(d, "name")) as f:
                    if f.read().strip() != "coretemp":
                        continue
            except OSError:
                continue
            package, cores = None, []
            for name in os.listdir(d):
                if not (name.startswith("temp") and name.endswith("_input")):
                    continue
                with open(os.path.join(d, name)) as f:
                    c = int(f.read().strip()) / 1000.0
                try:
                    with open(os.path.join(d, name.replace("_input", "_label"))) as f:
                        label = f.read().strip()
                except OSError:
                    label = ""
                if label.startswith("Package"):
                    package = c
                else:
                    cores.append(c)
            if package is not None or cores:
                return {"package_c": package if package is not None else max(cores),
                        "core_max_c": max(cores) if cores else package}
        for z in sorted(os.listdir(os.path.join(root, "thermal"))):
            d = os.path.join(root, "thermal", z)
            try:
                with open(os.path.join(d, "type")) as f:
                    if f.read().strip() != "x86_pkg_temp":
                        continue
                with open(os.path.join(d, "temp")) as f:
                    c = int(f.read().strip()) / 1000.0
                return {"package_c": c, "core_max_c": c}
            except OSError:
                continue
    except OSError:
        pass
    return None


def _read_int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def read_throttle(root: str = CPU_ROOT, class_root: str = CLASS_ROOT) -> dict | None:
    """cpu0's package throttle counters, plus the intel_powerclamp idle-injection state.

    {"count": events since boot, "total_ms": time throttled since boot (None if absent),
     "clamp": powerclamp cur_state (0 = not injecting; None without the driver)}.
    None when the kernel has no thermal_throttle directory (a VM, another CPU)."""
    d = os.path.join(root, "cpu0", "thermal_throttle")
    count = _read_int(os.path.join(d, "package_throttle_count"))
    if count is None:
        return None
    return {"count": count, "total_ms": _read_int(os.path.join(d, "package_throttle_total_time_ms")),
            "clamp": read_powerclamp(class_root)}


def read_powerclamp(root: str = CLASS_ROOT) -> int | None:
    """intel_powerclamp's cur_state (idle injection, percent): thermald runs --adaptive and
    may inject idle, which would stall the drive thread. Negative (some kernels) = off = 0."""
    try:
        devs = sorted(os.listdir(os.path.join(root, "thermal")))
    except OSError:
        return None
    for z in devs:
        if not z.startswith("cooling_device"):
            continue
        d = os.path.join(root, "thermal", z)
        try:
            with open(os.path.join(d, "type")) as f:
                if f.read().strip() != "intel_powerclamp":
                    continue
        except OSError:
            continue
        v = _read_int(os.path.join(d, "cur_state"))
        return None if v is None else max(0, v)
    return None


class ThrottleRate:
    """Throttle events per minute over the interval between two reads (the 5 s chip
    refresh). The first read has nothing to compare with: per_min None. A counter that
    went DOWN was reset (a reboot under a long-lived reader): start again from it."""

    def __init__(self) -> None:
        self._prev: tuple[float, int, int | None] | None = None

    def update(self, now: float, sample: dict | None) -> dict | None:
        if sample is None:
            self._prev = None
            return None
        out = dict(sample, per_min=None, ms_per_min=None)
        prev, self._prev = self._prev, (now, sample["count"], sample.get("total_ms"))
        if prev is None or now <= prev[0] or sample["count"] < prev[1]:
            return out
        dt_min = (now - prev[0]) / 60.0
        out["per_min"] = (sample["count"] - prev[1]) / dt_min
        if sample.get("total_ms") is not None and prev[2] is not None and sample["total_ms"] >= prev[2]:
            out["ms_per_min"] = (sample["total_ms"] - prev[2]) / dt_min
        return out
