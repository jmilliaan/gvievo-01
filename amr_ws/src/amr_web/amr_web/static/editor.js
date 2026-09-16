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
    const p = poseAfter(route.steps.length); if (!p) { log('set the start pose first', 'err'); return; }
    const c = Math.cos(p.yaw), s = Math.sin(p.yaw), along = (w[0] - p.x) * c + (w[1] - p.y) * s;
    if (along < 0.05) { log('a straight only goes forward along the heading; use a turn to change direction', 'err'); return; }
    snapshot(); route.steps.push({ id: nextId(), type: 'straight', to: { x_m: p.x + c * along, y_m: p.y + s * along } }); refresh();
  }
};
document.querySelectorAll('button.turn').forEach(b => b.addEventListener('click', () => {
  if (!route.start) { log('set the start pose first', 'err'); return; }
  snapshot(); route.steps.push({ id: nextId(), type: 'rotate', direction: b.dataset.dir, angle_deg: +b.dataset.ang }); refresh();
}));
$('tool-start').onclick = () => setTool(view.tool === 'start' ? null : 'start');
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
  lastResult = data; showResult(data); log(status === 200 ? `valid: ${data.compiled.total_length_m.toFixed(2)} m, ${data.compiled.steps.length} steps` : `invalid: ${data.issues.length} issue(s)`, status === 200 ? '' : 'err'); refresh();
};
$('btn-save').onclick = async () => {
  const { status, data } = await api(`/api/maps/${mapId}/${mapRev}/routes/save`, payload());
  if (status === 200) { savedRef = { route_id: data.route_id, revision: data.revision }; log(`saved ${data.route_id} rev${data.revision} (${data.sha256.slice(0, 12)})`); await reloadRouteList(); }
  else { lastResult = data; showResult(data); refresh(); }
};
$('btn-mission').onclick = async () => {
  if (!savedRef) { log('save a revision first', 'err'); return; }
  const { status, data } = await api('/api/missions', { map_id: mapId, map_revision: mapRev, route_id: savedRef.route_id, route_revision: savedRef.revision });
  if (status === 200) log(`mission ${data.mission_id} created`);
};
function showResult(d) {
  const lines = [];
  if (d.issues && d.issues.length) d.issues.forEach(i => lines.push(`✗ ${i.step_id ? i.step_id + ': ' : ''}${i.message}`));
  if (d.compiled) lines.push(`length ${d.compiled.total_length_m.toFixed(2)} m, turns ${d.compiled.total_turn_deg.toFixed(0)}°, closes: ${d.compiled.closes}`);
  if (d.ok) lines.unshift('✓ valid');
  $('ed-result').textContent = lines.join('\n') || '—';
}
function refresh() {
  const bad = new Set((lastResult && lastResult.issues || []).map(i => i.step_id));
  $('ed-steps').innerHTML = route.steps.map(s => `<li class="${bad.has(s.id) ? 'bad' : ''}">${s.id}: ${s.type === 'straight' ? `straight → (${s.to.x_m.toFixed(2)}, ${s.to.y_m.toFixed(2)})` : `${s.direction.toUpperCase()} ${s.angle_deg}°`}</li>`).join('');
  $('ed-repeat').value = route.repeat_count; view.draw();
}
view.overlays.push((c, v) => {
  if (!route.start) { if (v._preview) v.arrow(v._preview.x, v._preview.y, v._preview.yaw, 1.0, '#f0ad4e'); return; }
  const bad = new Set((lastResult && lastResult.issues || []).map(i => i.step_id));
  let p = poseAfter(0);
  v.arrow(p.x, p.y, p.yaw, 1.0, '#2ecc71'); if (footprint) v.footprint(p.x, p.y, p.yaw, footprint.polygon, '#2ecc7188');
  route.steps.forEach((s, i) => {
    const q = poseAfter(i + 1);
    if (s.type === 'straight') { v.line(p.x, p.y, q.x, q.y, bad.has(s.id) ? '#e74c3c' : '#3d8bfd', 3); v.text((p.x + q.x) / 2, (p.y + q.y) / 2, s.id, '#9cc'); }
    else { v.dot(q.x, q.y, bad.has(s.id) ? '#e74c3c' : '#f0ad4e', 6); v.text(q.x, q.y, `${s.id} ${s.direction.toUpperCase()} ${s.angle_deg}°`, '#f0ad4e'); v.arrow(q.x, q.y, q.yaw, 0.6, '#f0ad4e'); if (footprint) v.footprint(q.x, q.y, q.yaw, footprint.polygon, '#f0ad4e66'); }
    p = q;
  });
  if (v._preview && v.tool === 'start') v.arrow(v._preview.x, v._preview.y, v._preview.yaw, 1.0, '#f0ad4e');
  const st = lastState && lastState.localization;
  if (st && st.state_name !== 'UNLOCALIZED' && lastState.run && lastState.run.pose_x !== undefined) v.arrow(lastState.run.pose_x, lastState.run.pose_y, lastState.run.pose_yaw, 0.8, '#fff');
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
  log(`loaded ${rid} rev${rrev}${data.ok ? '' : ' (INVALID on this map revision)'}`, data.ok ? '' : 'err');
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
