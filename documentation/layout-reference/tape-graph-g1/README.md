# Tape graph g1 on rev-boiacca-map-01 rev1

Rendered on the survey map `~/amr_maps/rev-boiacca-map-01/rev1/map.pgm` (0.05 m/px), in the
map frame AMCL localises in. Map data, passes and marks live on the vehicle; these images are
snapshots for reference. Plan: `manuals/tracked-plan-4-position-engine.md` (sections 9–10).

| Image | Shows | Data |
|---|---|---|
| `c-mru-pass-overview.png` | the whole C-MRU circuit as driven: outbound blue, inbound orange, junction anchors, fork episodes (x), kink pivots (triangles), U-turn, HOME-N | pass `C-MRU-2026-10-24T142823` |
| `c-mru-pass-home.png` | the same, zoomed on the HOME complex (bay, R717 loop, J-N, X1, J-STEM, J-SPLIT). The orange hump before HOME-N is a manual detour around an obstacle | same pass |
| `marks-overview.png` | every mark on the g1 legs, by kind (stop out / stop in / U-turn point / reference) | `marks.json`, graph g1, 2026-10-25 |
| `marks-home-junctions.png` | the HOME complex: M1 = ATT, M2 before J-N, M5 before J-ML | same |
| `marks-mru-line.png` | the MRU line, J-ML to the tape end, with every mark and role | same |
| `marks-mru-machines.png` | the four machines close up: MW (release empty), UT (U-turn point), ME (attach full) | same |

`draw_marks.py` redraws the four `marks-*` images from the vehicle's files (PIL); run it from a
scratch directory and copy the PNGs here.

Junction anchors (map frame, m): J-BMERGE (2.36, -1.41), J-N (-10.61, -1.38), X1 (-11.77, 1.08),
J-ML (-10.56, 12.45), J-STEM (-11.69, 0.72), J-SPLIT (-10.59, -0.31).

## Marks and roles (operator rules, 2026-10-25)

| Mark | Role | Leg, s | Rule |
|---|---|---|---|
| M1 | ATT | J-BMERGE→J-N 11.92 m | trolley attach point |
| M2 | - | J-BMERGE→J-N 17.30 m | outbound branch J-N: right MRU, straight BTU, left STU (STU later) |
| M5 | - | X1→J-ML 9.25 m | J-ML: BTU inbound joins; MRU out straight/right, in straight/left |
| M8–M11 | MW-1…MW-4 | J-ML→U-MRU 45.51 / 55.81 / 66.35 / 72.37 m | MRU1…4 release empty (marked while driving) |
| M12–M15 | ME-1…ME-4 | U-MRU→J-ML 32.43 / 22.13 / 11.58 / 5.57 m | MRU1…4 attach full: 2 m from the release, toward home (`mark_offset M8 2.0 M12` …) |
| M16–M18 | UT-MRU1…3 | J-ML→U-MRU 46.91 / 57.21 / 67.75 m | MRU1…3 U-turn point: 1.4 m from the release, toward the line's end (`mark_along M8 1.4 M16` …) |
| - | U-MRU | tape end, 75.61 m | MRU4 has no U-turn point: it turns at the tape end |

M3 (unused) and M4, M6, M7 (old zone ends: high speed is now areas drawn on the map) are deleted.
The first M12 (75.25 m, near the tape end) was briefly UT-MRU4 and is deleted too. Backups:
`marks-2026-10-25-*.bak.json` and `stations-2026-10-25-*.bak.json` beside `marks.json`.

All ten MRU trips (each machine alone, every pair) compile on g1 with these stations, with HOME-N
stood in by the 14:28 pass's start. HOME-N itself is not taught yet.
