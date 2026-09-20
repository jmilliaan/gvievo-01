#!/usr/bin/env python3
"""Entry point for the AGV controller.

    python3 main.py                 # 0.0.0.0:5000, reachable from the LAN
    python3 main.py --port 5001
    AGV_PROFILE=agv-02 python3 main.py

*** THIS MOVES HARDWARE, and it has no authentication. *** Anyone who can reach
the port can drive the AGV. Keep it on a trusted network.

Thin on purpose. Everything real lives in app/server.py; this exists so the
systemd unit's ExecStart names a path at the repo root that never moves again,
however the tree below it is reorganised.

Run it from the repo root, or install the library first (`pip install -e .`).
As a script, sys.path[0] is this file's directory, which is the repo root, so
both `app` and `agv_core` resolve without any path surgery here. The layer-dir
inserts this file used to carry went with the move to the agv_core package.
"""
import sys

from app.server import main

if __name__ == "__main__":
    sys.exit(main() or 0)
