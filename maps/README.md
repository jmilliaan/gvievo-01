# Map snapshots

Copies of saved map revisions from the vehicle, for viewing away from it. The
vehicle does **not** load maps from here: the live store is `~/amr_maps` on the
robot (`AMR_MAPS_DIR`), and that stays the source of truth.

Each `<map_id>/rev<N>/` holds:

- `map.png`: preview of `map.pgm` (white = free, black = occupied, grey = unknown)
- `map.pgm`, `map.yaml`: the occupancy grid as saved (0.05 m per pixel)
- `manifest.yaml`: start pose, survey closure review, and the sha256 of every bundle file

`posegraph.posegraph` / `posegraph.data` (slam_toolbox's serialised graph, ~55 MB per
revision) are left out: nothing reloads them, and they would bloat the history. The
manifest still lists their hashes, so this copy is not a complete bundle and cannot
be copied back into `~/amr_maps` as-is.

| Map | Rev | Saved | Start | Closure | Note |
|---|---|---|---|---|---|
| kyb-map-01 | 1 | 2026-11-02 15:42 | HP-no-tape | dx 0.09 m, dy −0.05 m, dyaw −1.0° | seams ok |
