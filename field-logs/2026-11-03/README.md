# Vehicle logs, 2026-11-03 09:09:43 – 15:29:34 WIB

Copied off MCQ4-4 (`gvipc-ce`, branch `kyb-trackless`) in two passes. The first, at 15:09,
covered the 6 hours before it. The second, at 15:29, added what had been written since,
without copying anything twice (see "How the second pass was added"). These are evidence,
not source. The vehicle keeps writing its own copies (see "Source" below), and those
rotate, so they will diverge from these files.

The window holds every boot and service start of the day: 09:30, 09:42, 10:10, 11:52,
13:08, 13:30, 13:43, 14:30, 14:43, 15:10. The supervisor reported power loss at 09:30, 09:42
and 13:08 (the last one: "Power was lost at 11:55 while STOPPING").

| Here | Source on the vehicle | What it covers |
|---|---|---|
| `events.jsonl` | `~/.amr/logs/events.jsonl`, lines with `t` in the window | Alarms-page event log, 2365 events from 09:30:02. Complete for the window |
| `operations.jsonl` | `~/.amr/operations.jsonl`, lines with `t` in the window | Supervisor mode/layer operations, 36 lines |
| `journal-amr-service.txt` | `journalctl -u amr.service` | Supervisor output: mode changes, starts/stops, power-loss warnings. Complete |
| `journal-kernel.txt` | `journalctl -k` | Kernel: NIC links (enp1s0 DIO, enp2s0 nanoScan3, enp3s0 GLS621), CAN adapter, USB |
| `amr-logs/` | `~/.amr/logs/{base,layer,web,foxglove}.log*` | Per-node output, one file per service session (`amr_bringup/logs.py` keeps 5 old ones). **Starts at about 11:52**: the 09:30–11:52 sessions had already rotated out |
| `ros-log/` | `~/.ros/log/` entries written in the window | One folder per ROS launch, plus per-process `*.log`. This does cover the morning sessions |
| `route/` | `~/amr_maps/kyb-map-02/routes/route-itg-02/rev1.yaml` and `~/amr_maps/missions/kyb-map-02_rev3_route-itg-02_rev1.yaml` | The one route run today (every run in the logs is this mission). 32 steps, so the log's "step N of 32" maps onto the route's `steps:` list. Its sha256 matches the mission's. The map it is drawn on (`kyb-map-02` rev3, sha `97cb9e92…`) is already in the repo at `maps/kyb-map-02/rev3/` |
| `params/` | the repo, HEAD and the working tree | The motion parameters (speeds, accelerations, Nav2) and which session ran which set. See `params/README.md`. Actual speed and pose were **not** logged |

## `amr-logs/` numbering

Names follow the vehicle's own numbering as of 15:29: `X.log` is the session that started
at 15:10:34, `.1` the one before it, and so on. `.6` is the oldest (base.log.6 is the
11:52 session) and has already rotated off the vehicle. `base`, `foxglove` and `web` turn
over at each service start; `layer` also turns over at each mapping/navigation layer
change. `X.log` stops at 15:29, because the vehicle was still writing it.

## How the second pass was added

- The four files that were still being written at 15:09 were checked byte-for-byte as
  prefixes of their rotated successors. Only the bytes after the first copy were appended.
  The older files were checked identical and only renamed.
- `events.jsonl`, `operations.jsonl`: only lines with `t` after the newest one already
  here were appended. The journals: only lines not already present. No line in any of the
  four occurs twice.
- `ros-log/`: new launch files were copied. Files that had grown were checked as prefixes
  and only their new tail was appended.

The files in `amr-logs/` and `ros-log/` are copied whole, so they can hold a few lines from
before 09:09.
