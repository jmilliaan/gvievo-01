// Tape graph over the map (2026-10-24): the taught legs (or, before a graph is published, the
// newest recorded pass), the junction anchors, the stations and the marks - drawn only on the
// map revision they were taught on. Read-only: /api/line/graph, polled every 5 s while visible.
let tapeGraph = null;
function graphOverlay(view) {
  view.overlays.push((c, v) => {
    const g = tapeGraph;
    if (!g || !g.available || !v.meta) return;
    if (v.meta.map_id !== g.map_id || +v.meta.revision !== +g.map_revision) return;
    (g.areas || []).forEach(a => { v.fillPolygon(a.polygon, alpha(INK.preview, 0.18), INK.turn); v.text(a.polygon[0][0], a.polygon[0][1], `HIGH ${a.id}`, INK.turn); });
    g.legs.forEach(l => v.polyline(l.pts, alpha(INK.route, 0.85), 3));
    if (g.pass) { c.setLineDash([6, 4]); v.polyline(g.pass.pts, alpha(INK.route, 0.85), 3); c.setLineDash([]); }
    g.anchors.forEach(a => { v.dot(a.x, a.y, INK.turn, 5); v.text(a.x, a.y, a.id, INK.turn); });
    g.stations.forEach(s => { v.dot(s.x, s.y, INK.accent, 6); v.text(s.x, s.y, s.id, INK.accent); });
    g.marks.forEach(m => { v.dot(m.x, m.y, INK.preview, 5); v.text(m.x, m.y, m.label ? `${m.id} ${m.label}` : m.id, INK.ink3); });
    const what = g.legs.length ? `TAPE GRAPH g${g.graph_revision}` : (g.pass ? `PASS ${g.pass.name}` : '');
    if (what) v.label(`${what} · ${g.marks.length} marks`, INK.ink3, 3);
  });
}
function pollGraph(view) {
  let last = '';
  every(5000, async () => {  // a failed fetch keeps the last drawing
    const { status, data } = await apiGet('/api/line/graph');
    if (status === 200) {
      const key = JSON.stringify(data);
      if (key !== last) { last = key; tapeGraph = data; view.draw(); }
    }
  }, { visibleOnly: true });
}
