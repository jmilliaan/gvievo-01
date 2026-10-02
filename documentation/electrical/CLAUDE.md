# diagrams/ — JIS electrical sheets

Before any work in this folder (new sheet, edit, sketch or photo of a schematic), read `agent/SKILL.md` and follow its workflow. It points to everything else.

Short version:
- Sheets are HTML/SVG built on `kit/jis-sheet.js`; copy a template from `sheets/_template-*.html`, fill data, don't restyle.
- Interpret the source first (`agent/templates/interpretation.md`), wait for confirmation, then build.
- Never invent values: doubtful → `'?value'`, missing → `'«placeholder»'` (both render red).
- The deliverable is **HTML only**. Check the render with `agent/scripts/preview.ps1` (throw-away PNG in `%TEMP%`) against `agent/reference/checklist.md`. Do not write PNG/PDF into the project unless the user asks; then use `agent/scripts/export.ps1`.
- Never publish or upload the sheets or source photos.
