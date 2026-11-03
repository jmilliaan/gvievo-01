# Applying a map edits file (`*-edits.json`) on the AGV

This is for whoever applies these files on the vehicle PC, including a coding agent that
has no other context. It explains:

- what the file is;
- how to apply it;
- how to check the result;
- what not to do.

Nothing here moves the vehicle.

## Background: how maps are stored on the AGV

- **Where the live maps are.** The vehicle's maps live in **`~/amr_maps`**
  (`AMR_MAPS_DIR=/home/gvipc-evo-01/amr_maps`, from `amr_ws/deploy/amr.env`). They are
  stored as `~/amr_maps/<map_id>/rev<N>/`, and each holds `map.pgm` + `map.yaml` (a 5 cm
  occupancy grid), `posegraph.*`, and `manifest.yaml`.
- **Revisions never change.** `manifest.yaml` lists the sha256 of every file in the
  revision. Its top-level `sha256` is the revision's **identity**. Routes, floor-label sets
  and missions store that identity and refuse a map whose files no longer match it. **So
  never edit, overwrite or delete files under `~/amr_maps` by hand.** An edited map is
  always a **new** revision, made by the vehicle's own code.
- **The repo copy is not the live store.** `maps/` in this repo holds read-only snapshots
  of revisions (without the large `posegraph.*` files) for viewing and editing on a
  laptop. The vehicle never loads maps from `maps/`. Do not copy them into `~/amr_maps`.

## What the edits file is

The file was made on a laptop with a desktop map editor. It is a **recipe**, not a map: an
ordered list of polygon operations to apply to one parent revision. The vehicle replays
that list and publishes the result as `rev<N+1>`. The parent revision stays untouched.

Fields:

| Field | Meaning | Read by the vehicle? |
|---|---|---|
| `format`, `version` | Always `"amr-map-edits"`, `1`. Identifies the file | no |
| `parent.map_id`, `parent.revision` | The map and revision the edits were drawn on. The file sits in that snapshot's folder, `maps/<map_id>/rev<N>/` | no: you pass them as `--map` / `--rev` |
| `parent.sha256` | The parent's identity (`sha256` in its `manifest.yaml`) when the edits were drawn | **no: check it yourself** (step 1 below) |
| `created`, `note` | When it was made, and why. `map_edit` takes the note from `--note`, so pass it there | no |
| `apply` | The command line, as a hint | no |
| `summary` | The expected effect, computed on the laptop with the vehicle's own code: `cells_changed`, `now_free`, `now_occupied`, `now_unknown`, `dynamic_added`, `dynamic_cleared` | no: use it to **verify** (step 4) |
| `groups` | How the editor grouped the ops for its undo list | no |
| **`ops`** | **The edits: this is all the vehicle applies** | **yes** |

Each op is a polygon in **map metres**. That is the `map` frame, the same coordinates as
`map.yaml`'s origin and the manifest's start pose. A polygon has 3–64 `[x, y]` vertices.

| Op | Effect on the new revision |
|---|---|
| `{"op": "paint", "value": "occupied", "polygon": …}` | Cells become obstacle (100). Used for things the lidar missed (glass, rails) |
| `{"op": "paint", "value": "free", "polygon": …}` | Cells become free floor (0). An assertion that it is open floor: routes may then pass through it |
| `{"op": "paint", "value": "unknown", "polygon": …}` | Cells become unknown (−1). The "safe erase": unknown still blocks route approval unless it is inside a dynamic area |
| `{"op": "dynamic", "polygon": …}` | Marks a dynamic area (trolleys, parked forklifts) in `dynamic.pgm`. Map cells are unchanged |
| `{"op": "undynamic", "polygon": …}` | Clears a dynamic mark |

Rules:

- A cell is affected when its **centre** lies inside the polygon (even-odd rule).
- Ops apply **in order**, so a later op wins where polygons overlap.
- The vehicle refuses a file with more than 500 ops, or one whose result equals the parent.

Code: the op format and rasterising are in `amr_ws/src/amr_maps/amr_maps/edit.py`. The new
revision is made by `amr_ws/src/amr_mission/amr_mission/map_bundle.py` (`derive_edit`)
through the CLI `amr_ws/src/amr_mission/amr_mission/map_edit.py`. The web app's Maps →
Edit areas page uses the same path.

## How to apply it

The commands assume the repo checkout that `amr.service` runs from. That is
`/home/gvipc-evo-01/agv_can` (see `systemctl cat amr.service`); adjust `REPO` if this
checkout is elsewhere. The service may keep running: the write takes a per-map lock.

```bash
REPO=/home/gvipc-evo-01/agv_can          # this repo on the AGV
FILE=$REPO/maps/kyb-map-02/rev1/kyb-map-02-rev1-edits.json
MAP=kyb-map-02; REV=1                     # = parent.map_id, parent.revision in the file
cd $REPO && git pull
```

**1. The parent on the vehicle must be the revision the edits were drawn on.** The two
hashes printed must be equal. If they differ, **stop**: the edits were drawn on a different
map and would land in the wrong places.

```bash
grep '^sha256:' ~/amr_maps/$MAP/rev$REV/manifest.yaml
python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['parent']['sha256'])" "$FILE"
```

**2. Don't apply it twice.** Each applied edit leaves an `edits.json` in the revision it
made, naming its parent. If this prints a revision whose `edits.json` has the same `ops`,
the file was already applied; do not apply it again.

```bash
grep -l "$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['parent']['sha256'])" "$FILE")" \
  ~/amr_maps/$MAP/rev*/edits.json 2>/dev/null
```

**3. Apply it.**

```bash
source /opt/ros/humble/setup.bash
source $REPO/amr_ws/install/setup.bash
ros2 run amr_mission map_edit --map $MAP --rev $REV --ops "$FILE" \
    --note "$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['note'])" "$FILE")"
```

It prints `<map> rev<N> from rev<REV>: <k> edits, <d> dynamic cells` and the new
revision's path. On a refusal it prints `map_edit: refused: <reason>` and exits 1, having
written nothing.

**4. Verify against the file's `summary`.** For example, for a file whose summary says
605 cells changed, all to free, the expected output is
`changed 605 free 605 occupied 0 unknown 0`:

```bash
NEW=2   # the revision map_edit printed
python3 - <<EOF
from amr_maps import grid as g
a = g.read("$HOME/amr_maps/$MAP/rev$REV/map.yaml").data
b = g.read("$HOME/amr_maps/$MAP/rev$NEW/map.yaml").data
d = a != b
print("changed", int(d.sum()), "free", int((b[d] == 0).sum()),
      "occupied", int((b[d] == 100).sum()), "unknown", int((b[d] == -1).sum()))
EOF
```

The counts must equal `summary.cells_changed`, `now_free`, `now_occupied` and
`now_unknown`. If the file has dynamic ops, also check that
`~/amr_maps/$MAP/rev$NEW/dynamic.pgm` exists. The new revision also contains
`edits.json` (the parent and the ops) and is listed in its own `manifest.yaml`.

## After applying

- **Routes do not move to the new revision.** Routes and missions are bound to the exact
  revision they were saved on, and keep running on the old one. To drive on the edited map,
  the operator opens **Routes** in the web app (port 5001) and selects the new revision.
  Then, for each route: load it, **Validate**, **Save revision**. Then create a new mission,
  and select the new revision on **Run**. Leave starting runs to the operator: autonomous
  motion needs the physical selector and Start button anyway.
- **Snapshot the new revision back to the repo** so the next laptop edit starts from it:
  copy `map.pgm`, `map.yaml`, `manifest.yaml` and `edits.json` (not `posegraph.*`) from
  `~/amr_maps/<map>/rev<N>/` to `maps/<map>/rev<N>/`, and add a row to
  [README.md](README.md). Commit only if asked.

## Don't

- Don't edit, copy into, rename or delete anything under `~/amr_maps` by hand.
- Don't apply a file to a revision other than its `parent` (step 1), or apply it twice
  (step 2).
- Don't "fix" a refused file by editing its `ops`. Report the refusal reason instead; the
  file is regenerated on the laptop.
