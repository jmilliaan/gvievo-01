// Route editor: constrained straight/turn tools over a MapView. Persists map metres,
// never pixels. Validation and saving happen on the robot (POST); nothing moves.
const view = new MapView(document.getElementById('ed-canvas'));
let mapId = null, mapRev = null, footprint = null, mapsIndex = [];
let route = { route_id: '', start: null, steps: [], repeat_count: 1, limits: { linear_mps: 0.30 } };
let history = [], future = [], lastResult = null, savedRef = null;
const $ = id => document.getElementById(id);

function snapshot() { history.push(JSON.stringify(route)); if (history.length > 100) history.shift(); future = []; }
function undo() { if (!history.length) return; future.push(JSON.stringify(route)); route = JSON.parse(history.pop()); refresh(); }
function redo() { if (!future.length) return; history.push(JSON.stringify(route)); route = JSON.parse(future.pop()); refresh(); }

function setTool(t) { view.tool = t; ['tool-start', 'tool-line'].forEach(id => $(id).classList.toggle('on', id === 'tool-' + t)); $('ed-hint').textContent = t === 'start' ? 'Click the start position, drag towards the heading, release.' : t === 'line' ? 'Click a point: the straight goes along the current heading to the projection of that point.' : 'Wheel = zoom, drag = pan.'; }

// Heading after the last step, from the authored primitives (same rules as the compiler).
function poseAfter(n) {
  if (!route.start) return null;
  let x = route.start.x_m, y = route.start.y_m, yaw = route.start.yaw_deg * Math.PI / 180;
  for (let i = 0; i < n; i++) {
    const s = route.steps[i];
    if (s.type === 'straight') { x = s.to.x_m; y = s.to.y_m; }
    else yaw += (s.direction === 'ccw' ? 1 : -1) * s.angle_deg * Math.PI / 180;
  }
  return { x, y, yaw };
}
function nextId() { let i = route.steps.length + 1; while (route.steps.some(s => s.id === 's' + i)) i++; return 's' + i; }

view.onDrag = (a, b, done) => {
  if (view.tool !== 'start') return;
  const yaw = Math.atan2(b[1] - a[1], b[0] - a[0]);
  if (done) { snapshot(); route.start = { x_m: a[0], y_m: a[1], yaw_deg: yaw * 180 / Math.PI }; refresh(); }
  else view._preview = { x: a[0], y: a[1], yaw };
};
view.onClick = w => {
  if (view.tool === 'start') { snapshot(); route.start = { x_m: w[0], y_m: w[1], yaw_deg: route.start ? route.start.yaw_deg : 0 }; refresh(); return; }
  if (view.tool === 'line') {
    const p = poseAfter(route.steps.length); if (!p) { log('set the start pose first', 'bad'); return; }
    const c = Math.cos(p.yaw), s = Math.sin(p.yaw), along = (w[0] - p.x) * c + (w[1] - p.y) * s;
    if (along < 0.05) { log('a straight only goes forward along the heading; use a turn to change direction', 'bad'); return; }
    snapshot(); route.steps.push({ id: nextId(), type: 'straight', to: { x_m: p.x + c * along, y_m: p.y + s * along } }); refresh();
  }
};
document.querySelectorAll('button.turn').forEach(b => b.addEventListener('click', () => {
  if (!route.start) { log('set the start pose first', 'bad'); return; }
  snapshot(); route.steps.push({ id: nextId(), type: 'rotate', direction: b.dataset.dir, angle_deg: +b.dataset.ang }); refresh();
}));
$('tool-start').onclick = () => setTool(view.tool === 'start' ? null : 'start');
// Most routes begin where the survey began: one press puts the route start on the map's
// survey mark (position and heading) instead of drawing it by hand.
$('btn-start-survey').onclick = () => {
  const st = view.meta && view.meta.start;
  if (!st || st.x_m === undefined) { log('this map has no survey start mark', 'bad'); return; }
  snapshot(); route.start = { x_m: st.x_m, y_m: st.y_m, yaw_deg: (st.yaw_rad || 0) * 180 / Math.PI }; refresh();
  log(`route start = survey start (${num(st.x_m, 2)}, ${num(st.y_m, 2)}, ${num(route.start.yaw_deg, 1)}°)${st.description ? ' — ' + st.description : ''}`);
};
$('tool-line').onclick = () => setTool(view.tool === 'line' ? null : 'line');
$('btn-undo').onclick = undo; $('btn-redo').onclick = redo;
$('btn-clear').onclick = () => { snapshot(); route.steps = []; refresh(); };
$('ed-repeat').onchange = e => { route.repeat_count = +e.target.value; };
$('ed-speed').onchange = e => { route.limits.linear_mps = +e.target.value; };

function payload() {
  return { schema_version: 1, route_id: $('ed-route-id').value.trim(), revision: 0,
           map: { id: mapId, revision: mapRev, sha256: '' }, frame_id: 'map',
           start: route.start || { x_m: 0, y_m: 0, yaw_deg: 0 }, limits: route.limits, steps: route.steps, repeat_count: route.repeat_count };
}
$('btn-validate').onclick = async () => {
  const { status, data } = await api(`/api/maps/${mapId}/${mapRev}/routes/validate`, payload());
  lastResult = data; showResult(data); log(status === 200 ? `valid: ${data.compiled.total_length_m.toFixed(2)} m, ${data.compiled.steps.length} steps` : `invalid: ${data.issues.length} issue(s)`, status === 200 ? '' : 'bad'); refresh();
};
$('btn-save').onclick = async () => {
  const { status, data } = await api(`/api/maps/${mapId}/${mapRev}/routes/save`, payload());
  if (status === 200) { savedRef = { route_id: data.route_id, revision: data.revision }; log(`saved ${data.route_id} rev${data.revision} (${data.sha256.slice(0, 12)})`); await reloadRouteList(); }
  else { lastResult = data; showResult(data); refresh(); }
};
$('btn-mission').onclick = async () => {
  if (!savedRef) { log('save a revision first', 'bad'); return; }
  const { status, data } = await api('/api/missions', { map_id: mapId, map_revision: mapRev, route_id: savedRef.route_id, route_revision: savedRef.revision });
  if (status === 200) log(`mission ${data.mission_id} created`);
};
function showResult(d) {
  const parts = [];
  parts.push(`<div class="chips" style="margin-bottom:8px"><span class="chip ${d.ok ? 'ok' : 'bad'}">${d.ok ? 'valid' : 'invalid'}</span></div>`);
  if (d.compiled) {
    parts.push(`<div class="tel-grid">${[['Length', num(d.compiled.total_length_m, 2), 'm'], ['Turns', num(d.compiled.total_turn_deg, 0), '°'],
      ['Closes', d.compiled.closes ? 'YES' : 'NO', 'loop']].map(([l, v, u]) => `<div class="tel"><span>${l}</span><b>${esc(v)}</b><i>${u}</i></div>`).join('')}</div>`);
  }
  if (d.issues && d.issues.length) {
    parts.push(`<div class="al-log" style="margin-top:8px">${d.issues.map(i => `<div class="al-row standing lv-error"><span class="al-lv">${esc(i.step_id || i.code || 'route')}</span>` +
      `<span class="al-msg">${esc(i.message)}</span></div>`).join('')}</div>`);
  }
  $('ed-result').innerHTML = parts.join('');
}
function refresh() {
  const bad = new Set((lastResult && lastResult.issues || []).map(i => i.step_id));
  $('ed-steps').innerHTML = route.steps.length ? route.steps.map(s => `<div class="row three${bad.has(s.id) ? ' lv-error' : ''}"><span class="k">${esc(s.id)}</span>` +
    (s.type === 'straight' ? `<span class="n">straight</span><span class="v">${num(+s.to.x_m, 2)}, ${num(+s.to.y_m, 2)}<i>m</i></span>`
                           : `<span class="n">rotate</span><span class="v">${esc(String(s.direction).toUpperCase())} ${esc(s.angle_deg)}<i>°</i></span>`) + '</div>').join('')
    : '<div class="none">no steps</div>';
  $('ed-repeat').value = route.repeat_count; view.draw();
}
// The areas validation checks (amr_navigation.footprint), drawn from the same polygon + margin.
// A straight sweeps the grown footprint box along the heading; a turn sweeps it through the
// signed angle: the outline is the convex hull of the grown polygon at headings 5 deg apart.
function grown() {
  const xs = footprint.polygon.map(p => p[0]), ys = footprint.polygon.map(p => p[1]), m = footprint.margin_m;
  return [Math.min(...xs) - m, Math.max(...xs) + m, Math.min(...ys) - m, Math.max(...ys) + m];
}
function sweptBox(pose, len) {
  const [x0, x1, y0, y1] = grown(), c = Math.cos(pose.yaw), s = Math.sin(pose.yaw);
  return [[x0, y0], [x1 + len, y0], [x1 + len, y1], [x0, y1]].map(p => [pose.x + c * p[0] - s * p[1], pose.y + s * p[0] + c * p[1]]);
}
function sweptTurn(pose, signed) {
  const [x0, x1, y0, y1] = grown(), pts = [], n = Math.max(1, Math.ceil(Math.abs(signed) / (Math.PI / 36)));
  for (let k = 0; k <= n; k++) {
    const h = pose.yaw + signed * k / n, c = Math.cos(h), s = Math.sin(h);
    [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].forEach(p => pts.push([pose.x + c * p[0] - s * p[1], pose.y + s * p[0] + c * p[1]]));
  }
  return hull(pts);
}
function hull(pts) { // Andrew monotone chain
  pts = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const p of pts) { while (lo.length > 1 && cross(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
  for (const p of pts.reverse()) { while (up.length > 1 && cross(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}
view.overlays.push((c, v) => {
  if (!route.start) { if (v._preview) v.arrow(v._preview.x, v._preview.y, v._preview.yaw, 1.0, INK.preview); return; }
  const bad = new Set((lastResult && lastResult.issues || []).map(i => i.step_id));
  let p = poseAfter(0);
  // What validation actually checks (footprint + margin): the standing footprint at the start,
  // the swept box of every straight, the swept hull of every turn. Faint, under the route;
  // red when that step failed.
  if (footprint) {
    const checked = (id, col) => alpha(bad.has(id) ? INK.stop : col, 0.35);
    v.dashed(sweptBox(p, 0), checked(null, INK.pose));
    let a = p;
    route.steps.forEach((s, i) => {
      const b = poseAfter(i + 1);
      if (s.type === 'straight') v.dashed(sweptBox(a, Math.hypot(b.x - a.x, b.y - a.y)), checked(s.id, INK.route));
      else v.dashed(sweptTurn(a, (s.direction === 'ccw' ? 1 : -1) * s.angle_deg * Math.PI / 180), checked(s.id, INK.turn));
      a = b;
    });
  }
  v.arrow(p.x, p.y, p.yaw, 1.0, INK.pose); if (footprint) v.footprint(p.x, p.y, p.yaw, footprint.polygon, alpha(INK.pose, 0.55));
  route.steps.forEach((s, i) => {
    const q = poseAfter(i + 1);
    if (s.type === 'straight') { v.line(p.x, p.y, q.x, q.y, bad.has(s.id) ? INK.stop : INK.route, 3); v.text((p.x + q.x) / 2, (p.y + q.y) / 2, s.id, INK.ink3); }
    else { v.dot(q.x, q.y, bad.has(s.id) ? INK.stop : INK.turn, 6); v.text(q.x, q.y, `${s.id} ${s.direction.toUpperCase()} ${s.angle_deg}°`, INK.turn); v.arrow(q.x, q.y, q.yaw, 0.6, INK.turn); if (footprint) v.footprint(q.x, q.y, q.yaw, footprint.polygon, alpha(INK.turn, 0.4)); }
    p = q;
  });
  if (v._preview && v.tool === 'start') v.arrow(v._preview.x, v._preview.y, v._preview.yaw, 1.0, INK.preview);
  const st = lastState && lastState.localization;
  const md = lastState && lastState.mode;
  const onActive = md && v.meta && md.active_map_id === v.meta.map_id && +md.active_map_revision === +v.meta.revision;  // R12
  if (onActive && st && st.state_name !== 'UNLOCALIZED' && lastState.run && lastState.run.pose_x !== undefined) v.arrow(lastState.run.pose_x, lastState.run.pose_y, lastState.run.pose_yaw, 0.8, INK.accent);
});
async function reloadRouteList() {
  const { data } = await apiGet(`/api/maps/${mapId}/${mapRev}`);
  const sel = $('ed-load'); sel.innerHTML = '<option value="">— new —</option>';
  Object.entries(data.routes || {}).forEach(([rid, revs]) => revs.forEach(r => { const o = document.createElement('option'); o.value = `${rid}/${r}`; o.textContent = `${rid} rev${r}`; sel.appendChild(o); }));
}
$('ed-load').onchange = async e => {
  if (!e.target.value) return;
  const [rid, rrev] = e.target.value.split('/');
  const { data } = await apiGet(`/api/maps/${mapId}/${mapRev}/routes/${rid}/${rrev}`);
  snapshot(); route = { route_id: data.route.route_id, start: data.route.start, steps: data.route.steps, repeat_count: data.route.repeat_count, limits: data.route.limits };
  $('ed-route-id').value = data.route.route_id; savedRef = { route_id: rid, revision: +rrev }; lastResult = data; showResult(data); refresh();
  log(`loaded ${rid} rev${rrev}${data.ok ? '' : ' (INVALID on this map revision)'}`, data.ok ? '' : 'bad');
};
$('ed-map').onchange = async e => {
  [mapId, mapRev] = e.target.value.split('/'); mapRev = +mapRev;
  await view.load(mapId, mapRev); await reloadRouteList();
  route = { route_id: $('ed-route-id').value, start: null, steps: [], repeat_count: 1, limits: { linear_mps: 0.30 } }; history = []; future = []; lastResult = null; savedRef = null; refresh();
};
(async () => {
  footprint = (await apiGet('/api/footprint')).data;
  mapsIndex = await fillMapSelect($('ed-map'));
  if ($('ed-map').options.length) { $('ed-map').selectedIndex = 0; $('ed-map').onchange({ target: $('ed-map') }); }
})();
