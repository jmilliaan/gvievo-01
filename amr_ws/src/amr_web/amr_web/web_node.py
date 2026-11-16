"""web_node: the HTTP server (waitress, serve.py) in the main thread, the rclpy adapter spinning behind it."""

from __future__ import annotations

import rclpy
from agv_core import paths

from amr_web import serve
from amr_web.adapter import RosAdapter, start_spinning
from amr_web.server import create_app


def main(args=None) -> None:
    rclpy.init(args=args)
    adapter = RosAdapter()
    adapter.declare_parameter("maps_dir", paths.maps_dir())
    adapter.declare_parameter("host", "0.0.0.0")
    adapter.declare_parameter("port", 5001)
    adapter.declare_parameter("wifi_iface", "wlp1s0")
    # role/PIN, event log, reports: same source as base.launch.py uses for its nodes
    adapter.declare_parameter("state_dir", paths.state_dir())
    maps_dir = adapter.get_parameter("maps_dir").value
    host, port = adapter.get_parameter("host").value, int(adapter.get_parameter("port").value)
    spinner = start_spinning(adapter)
    app = create_app(
        adapter,
        maps_dir,
        wifi_iface=str(adapter.get_parameter("wifi_iface").value),
        state_dir=str(adapter.get_parameter("state_dir").value),
    )
    log = adapter.get_logger()
    log.info(f"operator pages on http://{host}:{port}/  (maps_dir {maps_dir})")
    try:
        serve.serve(app, host, port, warn=log.warning)
    except KeyboardInterrupt:
        pass
    finally:
        spinner.stop()  # explicit executor shutdown + join before the context goes away
        for node in (adapter.calls, adapter):
            try:
                node.destroy_node()
            except Exception:  # noqa: BLE001
                pass
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
