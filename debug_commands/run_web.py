#!/usr/bin/env python3
"""Backwards-compatible shim. The real entry point is now ../app.py.

  python3 app.py                 # 0.0.0.0:5000, reachable from the LAN
  python3 app.py --port 5001
  python3 app.py --host 127.0.0.1

This file only exists so old commands and notes keep working; it takes the same
flags and does nothing of its own. Prefer app.py - that is what the
agv_controller systemd unit runs.
"""
import os
import sys

# app.py sits one level up, at the repo root. Running this script directly puts
# debug_commands/ on sys.path[0], not the root, so add the root explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main() or 0)
