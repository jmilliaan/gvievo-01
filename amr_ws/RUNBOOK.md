# AMR operator runbook

For the person at the vehicle. Engineering detail is in [README.md](README.md);
the safety model is in the [repo README](../README.md).

**What can move the vehicle.** Only the physical panel authorises motion:
selector **MANUAL** = the keyboard/teleop jog, selector **AUTO** + physical
**Start** = a loaded route. Nothing on a web page moves the vehicle. The E-stop
chain (lidar/encoders → FX3 → STO) is hardware and is not affected by anything
below.

**One controller at a time.** Three systemd units own the CAN bus and the panel
and they exclude each other — starting one stops the others:

| Unit | What it is | Web |
|---|---|---|
| `amr_nav` | normal operation: localise on a saved map, run drawn routes | http://192.168.2.20:5001 |
| `amr_mapping` | survey session: drive by hand, build a map, save it | http://192.168.2.20:5001 |
| `agv_controller` | legacy jog pad and diagnostics (no navigation) | http://192.168.2.20:5000 |

```bash
sudo systemctl start amr_mapping      # survey
sudo systemctl start amr_nav          # back to runtime
sudo systemctl start agv_controller   # legacy jog pad
systemctl status amr_nav              # which one is up
journalctl -u amr_nav -f              # its log
```

Which unit boots is set once: `sudo systemctl disable agv_controller && sudo systemctl enable amr_nav`.
Switch units only with the vehicle stopped. A switch de-energises the drives
for a few seconds (brakes engage) and re-arms at zero.

---

## 1. Survey a new map

Needs: the area clear, the vehicle at a marked floor position facing a marked
heading (chalk an axle-centre cross and an arrow — you must return to it).

1. `sudo systemctl start amr_mapping`. Wait ~10 s. Selector **MANUAL**.
2. Open http://192.168.2.20:5001/maps. Enter a map name and a description of
   the mark ("cross at bay 3, arrow toward the roller door"). **Start survey**.
   Refuses until: lidar fresh, gyro calibrated (needs 2.3 s stationary), wheels
   still.
3. Drive with the keyboard from a terminal on the vehicle:
   ```bash
   ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel_teleop -p speed:=0.2 -p turn:=0.3
   ```
   `i` forward, `,` back, `j`/`l` turn, `k` stop; release = stop. Keep to
   ≤0.3 m/s, slow round corners, revisit junctions from both directions.
   Watch the map grow in Foxglove (connect to `ws://192.168.2.20:8765`, 3D
   panel, frame `map`, topics `/map`, `/scan`).
4. **Return to the mark**, same position and heading (aim for 10 cm / 5°). Stop.
   Wait 5 s. Click **Returned to start**. The page shows the closure evidence:
   how far the SLAM pose is from where it thinks the mark is. If walls look
   doubled or the start area is smeared, drive another overlapping loop and
   return again.
5. **Save**. The bundle lands in `~/amr_maps/<name>/rev<N>/`. Saved maps are
   immutable; a re-survey makes a new revision.
6. `sudo systemctl start amr_nav` (stops mapping).

To survey the same area again later you must restart the unit: a survey cannot
be started twice in one session.

## 2. Draw a route

http://192.168.2.20:5001/editor, works while `amr_nav` is running, moves nothing.

1. Pick the map and revision.
2. Click the start point, drag for the start heading.
3. Add straights (click ahead along the heading) and turns (CW/CCW, 45/90/180/270).
   A turn only changes heading; the next straight goes the new way.
4. **Validate** — checks the footprint sweep along every line and the full turn
   circle at every pivot, against the map and `keepout.yaml` if present. Fix
   anything red.
5. **Save revision**, then **Create mission** (one route revision = one mission).

## 3. Run a route

http://192.168.2.20:5001/run

1. Put the vehicle at the route's start point, roughly facing the start heading
   (within 10 cm / 5° is the gate; closer is easier).
2. On the page, click the map at the vehicle's position and drag for heading —
   this is the initial pose for the localiser. Localisation shows **CHECKING**.
3. Selector **MANUAL**, jog forward half a metre and back so the localiser can
   converge. When the page shows *can confirm* and the scan overlay sits on the
   walls, click **Confirm** → **READY**.
4. Load the mission. State → **READY**.
5. Selector **AUTO**. Press physical **Start**. State → **EXECUTING**. Horn and
   lights are on whenever it moves.

While running:

| What you see | What it means | What to do |
|---|---|---|
| **BLOCKED** | something inside the next stretch of the route | remove it; when clear for 1 s click **Prepare resume**, then press **Start** |
| **PAUSED** | you clicked Pause | **Prepare resume**, then **Start** |
| **FAULT** | a sensor went stale, localisation was lost, a drive alarmed | vehicle is stopped; read the reason on the page; **Ack** returns it to IDLE — then relocalise (step 2–3) and reload |
| **DONE** | route finished | another run needs another **Start** |

Turning the selector to **MANUAL** mid-route aborts it. Closing the browser
does **not** stop a route — the vehicle owns it; use Pause, the selector, or
the E-stop.

## 4. Stopping and recovery

- **Stop now:** E-stop. Or selector to MANUAL (aborts), or Pause on the page.
- **Drives in alarm after an E-stop / power event:** the page shows FAULT with
  the alarm. Clearing a drive alarm is a **drive power cycle** — the software
  will not reset alarms (deliberate, ISO 3691-4). Then `sudo systemctl restart amr_nav`.
- **`8130h` on both drives** means the drives lost the PC's heartbeat: the
  control PC crashed or the unit was killed. Same recovery.
- **Vehicle will not arm** (log: `cannot arm ... retrying`): usually the safety
  chain (ETO) — check the E-stop, the lidar protective field, the FX3.
- **Panel dead** (page shows panel invalid, no authority): the DIO island at
  192.168.1.30 — cable, power. Nothing moves until it is back.
- **Nothing discovers anything** in a terminal: the shell is not in the vehicle's
  ROS domain. `source ~/agv_can/amr_ws/env/vehicle.sh` (new terminals get it
  automatically).

## 5. After a software update

```bash
cd ~/agv_can/amr_ws && colcon build --symlink-install && colcon test && colcon test-result
sudo ./deploy/install.sh          # only if a unit file changed
sudo systemctl restart amr_nav
```
