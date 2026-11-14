"""Which vehicle this PC is: the host name against the profile (manuals/agv-02-plan.md R3). Pure.

Both vehicles run one branch. A PC knows which one it is from one local line,
`AGV_PROFILE=agv-02` in `$AMR_STATE_DIR/vehicle.env` (read by amr_ws/env/vehicle.sh), never from a file
in the repo. A missing or unreadable file means the default profile, agv-01. On unit 2 that would boot
AGV-01's identity: its MQTT serial number, so the station would take two vehicles for one, and its
calibration. This check catches it before anything opens a device:

    host gvipc-evo-NN  must run  profile agv-NN      (alpha-setup.md: units differ by host name only)
    any other host     is not a vehicle: no check    (a dev box, the sim)

`python3 -m agv_core.identity` loads the profile (so a bad one fails here too) and exits 1 on a
mismatch. amr-supervisor.sh runs it before the supervisor starts; validate.sh runs it at install.
Nothing here is in the safety path: it refuses to start, it never permits anything.
"""

import re
import socket
import sys

HOST_RE = re.compile(r"gvipc-evo-(\d+)")


class IdentityError(Exception):
    """The host name and the profile name disagree."""


def expected_profile(hostname):
    """The profile a vehicle PC must run, from its host name, or None for a host that is no vehicle."""
    m = HOST_RE.fullmatch((hostname or "").strip().lower())
    return f"agv-{int(m.group(1)):02d}" if m else None


def check(hostname, profile_name):
    """None if this host may run this profile, else the reason (for the journal)."""
    want = expected_profile(hostname)
    if want is None or profile_name == want:
        return None
    return (f"host {hostname} must run profile {want}, but profile {profile_name} is loaded. Set "
            f"AGV_PROFILE={want} in $AMR_STATE_DIR/vehicle.env (manuals/agv-02-plan.md), or fix the "
            f"host name. Nothing was started.")


def main(argv=None):
    from agv_core import config  # noqa: PLC0415 - loads the profile the service would load

    host = socket.gethostname()
    why = check(host, config.PROFILE_NAME)
    if why:
        print(f"identity: {why}", file=sys.stderr)
        return 1
    print(f"identity: host {host}, profile {config.PROFILE_NAME}, "
          f"station serial {config.STATION_SERIAL_NUMBER}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
