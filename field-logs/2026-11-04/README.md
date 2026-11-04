# Vehicle logs, 2026-11-03 15:29:48 – 2026-11-04 15:07 WIB

Copied off MCQ4-4 (`gvipc-ce`, branch `kyb-trackless`) at 15:07 on 2026-11-04. This folder starts where
`../2026-11-03/` stops. These are evidence, not source. The vehicle keeps writing and rotating its
own copies, so they will diverge from these files.

Test results and findings for the day are in `hardware-test-results.md`.

| Here | Source on the vehicle | What it covers |
|---|---|---|
| `events.jsonl` | `~/.amr/logs/events.jsonl` | Alarms-page event log, 2945 events, only those after the last one in `../2026-11-03/`. No line appears in both folders. The 2 lines in the source that do not parse as JSON were left out |
| `operations.jsonl` | `~/.amr/operations.jsonl` | Supervisor mode and layer operations, 30 lines, same cutoff |
| `journal-amr-service.txt` | `journalctl -u amr.service` | Supervisor output from 11-03 15:29:35 |
| `journal-kernel.txt` | `journalctl -k` | Kernel from 11-03 15:29:35: NIC links (enp1s0 DIO, enp2s0 nanoScan3, enp3s0 GLS621), CAN adapter, USB |
| `amr-logs/` | `~/.amr/logs/{base,layer,web,foxglove}.log*` | Per-node output, one file per session. Vehicle's own numbering at copy time: `X.log` is the newest, and it stops at the copy. `foxglove.log*` stops on 11-04 at 09:05, when Foxglove was removed |
| `ros-log/` | `~/.ros/log/` entries written after 11-03 15:29:35 | One folder per ROS launch, plus per-process logs. 11 entries also exist in `../2026-11-03/ros-log/`, and these are the longer copies |
| `run-traces/` | `~/.amr/logs/run-traces/` | The always-on 2 Hz CSV for each run since the 14:25 restart. Wheel speeds are rad/s: multiply by the 0.09 m wheel radius for m/s |
| `recordings/<stamp>/` | `~/.amr/runs/<stamp>/` | `run_log.sh` output for 20261104-104146 and 20261104-111942: report, CSVs, logs, code state. **The bags are not here** (see below) |
| `route/`, `missions/` | `~/amr_maps/kyb-map-02/routes/`, `~/amr_maps/missions/` | `route-itg-02` rev 1–6 and `route-itg-02-salvage` rev 1–2, and every mission. All 8 route hashes match their missions |

Map rev 4 (rev 3 plus the ITG dynamic areas) is in `../../maps/kyb-map-02/rev4/`, without its pose graph
(122 MB), as with rev 3. The vehicle loads maps from `~/amr_maps`, not from the repo.

## Not in the repo

- **Raw bags.** `~/.amr/runs/20261104-104146/bag` (121 MB) and `.../20261104-111942/bag` (285 MB) are over
  GitHub's 100 MB file limit. They stay on the vehicle, and `recordings/<stamp>/bag-metadata.yaml` describes them.
- **Pose graph** of map rev 4, as above.
- **Runs from 12:09 to about 14:25** have no recording and no trace: only events and logs. That includes the
  rev 6 runs that finished DONE at 13:47, 14:03 and 14:18.

## Notes

- 20261104-111942's recorder stopped at 12:09, when the PC went down, so its report was generated later, at
  15:05 on 11-04, from the closed bag.
- `run_log.sh` copies only the tail of each log, so the logs in `recordings/` are partial. `amr-logs/` has them whole.
