// Run page: localisation state + initial pose tool, mission load and the coordinator
// controls. Motion itself is authorised only by the physical panel.
const view = new MapView(document.getElementById('run-canvas'));
const $ = id => document.getElementById(id);
let mapId = null, mapRev = null, footprint = null, preview = null;
let poseGen = null;  // the generation the operator saw when they picked up the pose tool

// Pose seeding and confirmation only make sense on the picture of the map the vehicle is
// running: coordinates drawn on map B would otherwise land in map A (R12). The server
// re-checks the identity against the live mode before anything is published.
function viewIsActive() {
  const m = lastState && lastState.mode;
  return !!(m && m.mode_name === 'NAVIGATION' && view.meta && m.active_map_id === view.meta.map_id &&
            +m.active_map_revision === +view.meta.revision);
}
function dropPoseTool() { view.tool = null; view._preview = null; $('tool-initialpose').classList.remove('on'); }

view.onDrag = (a, b, done) => {
  if (view.tool !== 'initialpose') return;
  const yaw = Math.atan2(b[1] - a[1], b[0] - a[0]);
  view._preview = { x: a[0], y: a[1], yaw };
  if (done) {
    if (!viewIsActive() || !lastState.mode || lastState.mode.generation !== poseGen) { log('the viewed map is not the active map (or the mode changed); pose not sent', 'err'); dropPoseTool(); return; }
    api('/api/localization/initialpose', { x_m: a[0], y_m: a[1], yaw_rad: yaw, map_id: view.meta.map_id, map_revision: view.meta.revision,
                                           sha256: view.meta.sha256, generation: poseGen }).then(r => { if (r.status === 200) log(r.data.message); });
    dropPoseTool();
  }
};
view.onClick = () => { log('drag from the position towards the heading', 'warn'); };
$('tool-initialpose').onclick = () => {
  if (view.tool) { dropPoseTool(); return; }
  if (!viewIsActive()) { log('select the active map in the view first', 'err'); return; }
  poseGen = lastState.mode.generation; view.tool = 'initialpose'; $('tool-initialpose').classList.add('on');
};
$('btn-loc-confirm').onclick = () => api('/api/localization/confirm').then(r => log(r.data.message, r.status === 200 ? '' : 'err'));
$('btn-loc-reset').onclick = () => api('/api/localization/reset').then(r => log(r.data.message));
$('btn-run-load').onclick = () => api('/api/mission/run', { mission_id: $('run-mission').value }).then(r => log(r.data.message, r.status === 200 ? '' : 'err'));
$('btn-run-pause').onclick = () => api('/api/mission/pause').then(r => log(r.data.message));
$('btn-run-resume').onclick = () => api('/api/mission/resume').then(r => log(r.data.message));
$('btn-run-abort').onclick = () => api('/api/mission/abort').then(r => log(r.data.message));
$('btn-run-ack').onclick = () => api('/api/mission/ack').then(r => log(r.data.message));

function fmt(o, keys) { return keys.map(k => `${k}: ${typeof o[k] === 'number' ? o[k].toFixed(3) : o[k]}`).join('\n'); }
let activeMap = null;  // {id, rev} the vehicle is actually running, from the supervisor
onState(st => {
  const m = st.mode;
  const nowActive = m && m.active_map_id ? { id: m.active_map_id, rev: m.active_map_revision } : null;
  if (JSON.stringify(nowActive) !== JSON.stringify(activeMap)) { activeMap = nowActive; preview = null; loadMissions(); }
  const onActive = viewIsActive();
  $('tool-initialpose').disabled = !onActive; $('btn-loc-confirm').disabled = !onActive;
  if (!onActive && view.tool === 'initialpose') dropPoseTool();
  if (view.tool === 'initialpose' && m && m.generation !== poseGen) dropPoseTool();
  $('active-map').textContent = m ? (m.mode_name === 'NAVIGATION' && activeMap ? `ACTIVE: ${activeMap.id} rev${activeMap.rev}` : `mode ${m.mode_name}${m.phase ? ' · ' + m.phase : ''} — no navigation map active`) : 'no supervisor';
  const l = st.localization;
  $('loc-state').textContent = l ? `${l.state_name}\n${l.reason}\n` + fmt(l, ['can_confirm', 'scan_match', 'scan_long', 'cov_xx', 'cov_yy', 'cov_yaw', 'scan_age_s', 'wheels_age_s', 'imu_age_s', 'tf_age_s']) : (st.localization_stale ? 'stale (from a replaced layer)' : 'no localisation (activate a map)');
  const r = st.run;
  $('run-state').textContent = r ? `${r.state_name}  run ${r.run_id}\n${r.reason}\n` + fmt(r, ['mission_id', 'step_index', 'step_id', 'remaining_turn_rad', 'cross_track_m']) : (st.run_stale ? 'stale (from a replaced layer)' : 'no executor (activate a map)');
  view.draw();
});
$('btn-activate').onclick = () => { if (!mapId) return; operation('/api/mode', { target: 'navigation', map_id: mapId, map_revision: mapRev }); };
$('btn-idle').onclick = () => operation('/api/mode', { target: 'idle' });
view.overlays.push((c, v) => {
  if (v._preview) v.arrow(v._preview.x, v._preview.y, v._preview.yaw, 1.0, '#f0ad4e');
  if (!viewIsActive()) return;  // executor pose and route preview are in the ACTIVE map's coordinates
  const r = lastState && lastState.run;
  if (r && r.pose_valid) { v.arrow(r.pose_x, r.pose_y, r.pose_yaw, 0.8, '#fff'); if (footprint) v.footprint(r.pose_x, r.pose_y, r.pose_yaw, footprint.polygon, '#ffffff88'); }
  if (preview) { let p = null; preview.steps.forEach(s => { if (s.type === 'straight') v.line(s.start[0], s.start[1], s.end[0], s.end[1], '#3d8bfd', 2); else v.dot(s.start[0], s.start[1], '#f0ad4e', 5); }); }
});
$('run-map').onchange = async e => { [mapId, mapRev] = e.target.value.split('/'); mapRev = +mapRev; dropPoseTool(); await view.load(mapId, mapRev); };
async function loadMissions() {
  const { data } = await apiGet('/api/missions'); const sel = $('run-mission'); sel.innerHTML = '';
  // only missions for the ACTIVE map can load; the executor refuses the rest anyway (P4)
  const usable = activeMap ? data.filter(m => m.map.id === activeMap.id && +m.map.revision === +activeMap.rev) : [];
  usable.forEach(m => { const o = document.createElement('option'); o.value = m.mission_id; o.textContent = `${m.mission_id}  (${m.map.id} rev${m.map.revision} · ${m.route.id} rev${m.route.revision})`; sel.appendChild(o); });
  if (!usable.length) { const o = document.createElement('option'); o.value = ''; o.textContent = activeMap ? `no missions for ${activeMap.id} rev${activeMap.rev}` : 'activate a map first'; sel.appendChild(o); }
}
$('run-mission').onchange = async e => {
  const wanted = e.target.value; preview = null;
  const m = (await apiGet('/api/missions')).data.find(x => x.mission_id === wanted); if (!m) { view.draw(); return; }
  const { data } = await apiGet(`/api/maps/${m.map.id}/${m.map.revision}/routes/${m.route.id}/${m.route.revision}`);
  if ($('run-mission').value !== wanted) return;  // another mission was picked meanwhile
  preview = data.compiled || null; view.draw();
};
(async () => {
  footprint = (await apiGet('/api/footprint')).data;
  await fillMapSelect($('run-map'));
  if ($('run-map').options.length) { $('run-map').selectedIndex = 0; $('run-map').onchange({ target: $('run-map') }); }
  await loadMissions(); if ($('run-mission').options.length) $('run-mission').onchange({ target: $('run-mission') });
})();

// live scan over the viewed map: meaningful only when the viewed map IS the active one
liveOverlay(view);
pollLive(view, { map: false });
jogpad(document.getElementById('jog-run'));
