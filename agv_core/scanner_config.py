"""The nanoScan3 driver addresses, from the profile (unified plan WP-P10, 2026-11-16).

The front unit's addresses are lidar.sensor_ip / host_ip / port, the rear unit's
rear.sensor_ip / host_ip / port. The launch files pass the result AFTER the driver's
yaml (nanoscan3.yaml, nanoscan3_rear.yaml), so the profile wins for these three
parameters and the yaml keeps everything else (frame, skip, angle window, feature
flags). Pure: no ROS, no file access. Read-only towards the scanner as well: the driver
writes only its UDP output settings, never the safety configuration.
"""

FRONT, REAR = "front", "rear"

# Which profile block feeds which scanner, as the config constants the loader exports.
_CONSTS = {
    FRONT: ("LIDAR_SENSOR_IP", "LIDAR_HOST_IP", "LIDAR_PORT"),
    REAR: ("REAR_SENSOR_IP", "REAR_HOST_IP", "REAR_PORT"),
}


def scanner_driver_params(section) -> dict:
    """A profile scanner block (lidar.* or rear.*: sensor_ip, host_ip, port) -> the
    sick_safetyscanners2 parameters that carry its addresses."""
    return {
        "sensor_ip": str(section["sensor_ip"]),
        "host_ip": str(section["host_ip"]),
        "host_udp_port": int(section["port"]),
    }


def section(cfg, which: str) -> dict:
    """The block for `which` (FRONT or REAR) out of a loaded profile: the agv_core.config
    module or the namespace config.load() returns."""
    get = cfg.__getitem__ if isinstance(cfg, dict) else lambda name: getattr(cfg, name)
    sensor_ip, host_ip, port = (get(name) for name in _CONSTS[which])
    return {"sensor_ip": sensor_ip, "host_ip": host_ip, "port": port}


def driver_params(cfg, which: str) -> dict:
    """scanner_driver_params() for FRONT or REAR of a loaded profile."""
    return scanner_driver_params(section(cfg, which))
