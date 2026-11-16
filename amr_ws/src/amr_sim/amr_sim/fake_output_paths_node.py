"""fake_output_paths_node: the nanoScan3's /output_paths in simulation (unified plan WP-T2).

SIM ONLY, never on a vehicle and never a field monitor: it emulates the scanner's certified
decision from the synthetic /scan (amr_sim.field_occupancy) so the sim drives the real mux and
follower through protective / warning stops. It refuses ROS_DOMAIN_ID 10 at start, and the
launch adds it only from the sim branch of base.launch.py with AMR_SIM_FIELDS=1
(test_launch_layers asserts it is in no real:=true launch).

    /scan                   LaserScan (in, scan_synth; laser frame = scanner frame)
    /output_paths           OutputPaths at the scan rate
    /sim/output_paths/set   amr_interfaces/srv/LineTeach  action: auto | clear | drop | invalid |
                            violate   arg (violate): protective | warning_1 | warning_2
"""

from __future__ import annotations

import yaml
from sensor_msgs.msg import LaserScan
from sick_safetyscanners2_interfaces.msg import OutputPaths

from amr_base.lean_node import LeanNode, run
from amr_base.qos import SENSOR_DATA
from amr_interfaces.srv import LineTeach
from amr_sim import field_occupancy as fo


def _refuse_vehicle_domain() -> None:
    import os  # noqa: PLC0415

    if os.environ.get("ROS_DOMAIN_ID", "").strip() == "10":
        raise SystemExit("fake_output_paths_node is a simulation: refused in the vehicle domain 10")


class FakeOutputPaths(LeanNode):
    def __init__(self) -> None:
        super().__init__("fake_output_paths", start_parameter_services=False)
        self.declare_parameter("fields_yaml", "")  # base.launch.py: scanner_fields.default_path()
        self.declare_parameter("min_points", 2)
        self.declare_parameter("debounce_samples", 2)
        with open(str(self.get_parameter("fields_yaml").value)) as fh:
            self.doc = yaml.safe_load(fh)
        self.min_points = int(self.get_parameter("min_points").value)
        self.debounce = fo.Debounce(int(self.get_parameter("debounce_samples").value))
        self.override = fo.AUTO
        self._pub = self.create_publisher(OutputPaths, "/output_paths", SENSOR_DATA)
        self.create_subscription(LaserScan, "/scan", self._on_scan, SENSOR_DATA)
        self.create_service(LineTeach, "/sim/output_paths/set", self._set)
        self.get_logger().warn("SIMULATED /output_paths from the scan: sim only")

    def _set(self, req, res):
        action, arg = req.action.strip(), (req.arg or "").strip()
        try:
            self.override = fo.check_override(f"{action}:{arg}" if action == fo.VIOLATE else action)
        except ValueError as e:
            res.ok, res.message = False, str(e)
            return res
        res.ok, res.message = True, f"/output_paths: {self.override}"
        self.get_logger().info(res.message)
        return res

    def _on_scan(self, scan: LaserScan) -> None:
        if self.override == fo.DROP:
            return
        pts = fo.points(scan.ranges, scan.angle_min, scan.angle_increment, scan.range_min, scan.range_max)
        occ = self.debounce.update(fo.occupied_now(pts, self.doc, self.min_points))
        forced = fo.override_occupancy(self.override)
        status, valid = fo.output_paths(forced or occ, self.doc, valid=self.override != fo.INVALID)
        m = OutputPaths()
        m.header.stamp = scan.header.stamp
        m.header.frame_id = scan.header.frame_id
        m.status, m.is_safe, m.is_valid = status, list(status), valid
        m.active_monitoring_case = int(self.doc.get("monitoring_case", 1))
        self._pub.publish(m)


def main() -> None:
    _refuse_vehicle_domain()
    run(FakeOutputPaths)


if __name__ == "__main__":
    main()
