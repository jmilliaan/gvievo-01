// Mapping page (2026-10-28): survey, continue a survey and the AMCL position, one canvas.
// While MAPPING the canvas is the live grid; otherwise the saved revision picked above it,
// with the live scan (on the AMCL map only), the tape graph and the pose being given.
// Nothing here authorises motion: the jog pad and the preset moves need selector MANUAL,
// a survey or a pose moves nothing.
const view = new MapView($('mp-canvas'));
const ENG = !!$('btn-survey-start');  // the Survey tab is rendered for the engineer only
let mapId = null, mapRev = null, mapToken = 0;
let surveying = false;   // mode MAPPING: the canvas shows the live grid
let poseGen = null;      // the generation the operator saw when they picked up the pose tool
let hint = null;         // continue-survey pose {x, y, yaw, source}
let busy = false;        // a survey operation is in flight

const deg = r => r * 180 / Math.PI;
const savedShown = () => !surveying && !!(view.meta && view.meta.map_id !== undefined);

// ---- the canvas: live grid or saved revision ----------------------------------------------

function hintText() {
  $('mp-hint').textContent = surveying
    ? 'Live map: grows while surveying · green = vehicle · red = current scan · drag = pan · +/− = zoom'
    : 'Saved map · orange arrow = the pose you give · dashed circle = survey start · drag = pan · +/− or wheel = zoom · fit = whole map';
}
async function showSaved(value) {
  if (!value) return;
  [mapId, mapRev] = value.split('/'); mapRev = +mapRev;
  const c = ++mapToken;
  dropTools(); setHint(null);
  if (surveying) return;  // picked while surveying: shown once the survey ends
  if (!(await view.load(mapId, mapRev)) || c !== mapToken) return;
  showInfo(); refresh();
}
$('mp-map').onchange = e => showSaved(e.target.value);

function setSurveying(on) {
  if (on === surveying) return;
  surveying = on;
  dropTools();
  $('mp-map').disabled = on;
  hintText();
  if (on) view.clearLive();          // the live poll fills it within a second
  else { view.clearLive(); showSaved($('mp-map').value); }
}

liveOverlay(view);
pollLive(view, { map: () => surveying });
graphOverlay(view);
pollGraph(view);
view.overlays.push((c, v) => {
  if (!savedShown()) return;
  const p = view.tool === 'initialpose' ? v._preview : hint;
  if (p) v.arrow(p.x, p.y, p.yaw, 1.0, INK.preview);
});

// One drag tool at a time: 'initialpose' (Position) or 'hint' (continue survey).
function dropTools() {
  view.tool = null; view._preview = null;
  $('tool-initialpose').classList.remove('on');
  if (ENG) $('tool-hint').classList.remove('on');
}
view.onDrag = (a, b, done) => {
  const yaw = Math.atan2(b[1] - a[1], b[0] - a[0]);
  if (view.tool === 'hint') {
    hint = { x: a[0], y: a[1], yaw, source: 'drawn' };
    if (done) { dropTools(); setHint({ x: a[0], y: a[1], yaw }, 'drawn'); }
    return;
  }
  if (view.tool !== 'initialpose') return;
  view._preview = { x: a[0], y: a[1], yaw };
  if (!done) return;
  if (!viewIsActive(view, lastState) || !lastState.mode || lastState.mode.generation !== poseGen) {
    log('the viewed map is not the AMCL map (or the mode changed); pose not sent', 'bad'); dropTools(); return;
  }
  sendPose(a[0], a[1], yaw, poseGen, '');
  dropTools();
};
view.onClick = () => log('drag from the position towards the heading', 'warn');

// ---- Position ----------------------------------------------------------------------------

function startMark() {
  const s = view.meta && view.meta.start;
  return s && s.x_m !== undefined ? { x: +s.x_m, y: +s.y_m, yaw: +(s.yaw_rad || 0) } : null;
}
function sendPose(x, y, yaw, gen, note) {
  api('/api/localization/initialpose', { x_m: x, y_m: y, yaw_rad: yaw, map_id: view.meta.map_id, map_revision: view.meta.revision,
                                         sha256: view.meta.sha256, generation: gen })
    .then(r => log(r.status === 200 ? r.data.message + note : r.data.message, r.status === 200 ? '' : 'bad'));
}
$('tool-initialpose').onclick = () => {
  if (view.tool) { dropTools(); return; }
  if (!viewIsActive(view, lastState)) { log('pick the AMCL map in the Map list first', 'bad'); return; }
  poseGen = lastState.mode.generation; view.tool = 'initialpose'; $('tool-initialpose').classList.add('on');
};
$('btn-pose-survey').onclick = () => {
  const s = startMark();
  if (!s) { log('this map has no survey start mark', 'bad'); return; }
  if (!viewIsActive(view, lastState)) { log('the viewed map is not the AMCL map; pose not sent', 'bad'); return; }
  dropTools();
  sendPose(s.x, s.y, s.yaw, lastState.mode.generation, ` (survey mark ${num(s.x, 2)}, ${num(s.y, 2)}, ${num(deg(s.yaw), 1)}°)`);
};
if ($('btn-at-home')) $('btn-at-home').onclick = () => act('/api/line/at_home');
$('btn-loc-confirm').onclick = () => act('/api/localization/confirm');
$('btn-loc-reset').onclick = () => act('/api/localization/reset');

// map -> pose -> confirm, in that order: which button is the operator's next
function steps(st, l) {
  const done = {
    map: !!st.loc_map,
    pose: !!(l && l.state_name !== 'UNLOCALIZED' && l.state_name !== 'LOST'),
    confirm: !!(l && l.state_name === 'READY'),
  };
  const now = ['map', 'pose', 'confirm'].find(k => !done[k]) || null;
  document.querySelectorAll('#loc-steps .step').forEach(el => {
    el.classList.toggle('done', done[el.dataset.step]);
    el.classList.toggle('now', el.dataset.step === now);
  });
}
const age = v => [num(v, 2), 's', v > 1.0 ? 'warn' : ''];
function position(st) {
  const m = st.mode, lm = st.loc_map, l = st.localization;
  tiles('active-map', [m
    ? (lm ? ['AMCL map', `${lm.map_id} rev${lm.map_revision}`, lm.layer === 'line' ? 'LINE · tape localization' : lm.layer, '', 'key']
      : ['AMCL map', 'NONE', `mode ${m.mode_name}${m.phase ? ' · ' + m.phase : ''}`, 'warn', 'key'])
    : ['AMCL map', '–', 'no supervisor', 'bad', 'key']]);
  steps(st, l);
  const onActive = viewIsActive(view, st);
  $('tool-initialpose').disabled = !onActive; $('btn-loc-confirm').disabled = !onActive;
  $('btn-pose-survey').disabled = !onActive || !startMark();
  if (view.tool === 'initialpose' && (!onActive || (m && m.generation !== poseGen))) dropTools();
  if (l) {
    tiles('loc-state', [
      ['State', l.state_name, l.operator_confirmed ? 'operator confirmed' : '—', LOC_LEVEL[l.state_name], 'key'],
      ['Can confirm', yesno(l.can_confirm), 'automatic checks', l.can_confirm ? '' : 'warn'],
      ['Scan match', num(l.scan_match, 3), 'fraction'],
      ['Scan long', num(l.scan_long, 3), 'fraction'],
    ]);
    tiles('loc-detail', [
      ['cov xx', num(l.cov_xx, 3), 'm²'], ['cov yy', num(l.cov_yy, 3), 'm²'], ['cov yaw', num(l.cov_yaw, 3), 'rad²'],
      ['scan age', ...age(l.scan_age_s)], ['wheels age', ...age(l.wheels_age_s)], ['imu age', ...age(l.imu_age_s)],
      ['tf age', ...age(l.tf_age_s)],
    ]);
    $('loc-reason').textContent = l.reason || '';
  } else {
    tiles('loc-state', [['State', st.localization_stale ? 'STALE' : '–', st.localization_stale ? 'from a replaced layer' : 'no AMCL running', st.localization_stale ? 'bad' : '', 'key']]);
    $('loc-detail').innerHTML = ''; $('loc-reason').textContent = '';
  }
}

// ---- Survey (engineer) -------------------------------------------------------------------

// "Returned to start" stores (pose - start) in the map frame: the survey ended at start + review
function surveyEnd() {
  const s = startMark(), r = view.meta && view.meta.review;
  if (!s || !r || r.dx_m === undefined) return null;
  return { x: s.x + +r.dx_m, y: s.y + +r.dy_m, yaw: Math.atan2(Math.sin(s.yaw + +r.dyaw_rad), Math.cos(s.yaw + +r.dyaw_rad)) };
}
function setHint(h, source) {
  hint = h ? { ...h, source } : null;
  if (!ENG) return;
  if (!hint) $('cs-hint').innerHTML = '<div class="none">no pose yet</div>';
  else tiles('cs-hint', [['x', num(hint.x, 2), 'm', '', 'key'], ['y', num(hint.y, 2), 'm'], ['heading', num(deg(hint.yaw), 1), '°'], ['from', source, '']]);
  refresh();
}
function showInfo() {
  if (!ENG || !view.meta) return;
  const m = view.meta, r = m.review || {};
  tiles('cs-info', [
    ['Map', `${m.map_id} rev${m.revision}`, r.continued_from ? `continued from rev${r.continued_from.revision}` : 'surveyed', '', 'key'],
    ['Size', `${num(m.width * m.resolution, 0)}×${num(m.height * m.resolution, 0)}`, 'm'],
    ['Closure', r.dx_m !== undefined ? `${num(+r.dx_m, 2)} / ${num(+r.dy_m, 2)}` : '–', r.dx_m !== undefined ? `m · ${num(deg(+r.dyaw_rad), 1)}°` : 'no review'],
    ['Pose graph', m.continuable ? 'saved' : 'none', m.continuable ? 'can be continued' : 'cannot be continued', m.continuable ? 'ok' : 'bad'],
  ]);
}
function refresh() {
  view.draw();
  if (!ENG) return;
  for (const id of ['btn-survey-start', 'btn-survey-returned', 'btn-survey-save', 'btn-survey-abort']) $(id).disabled = busy;
  $('btn-cs-start').disabled = busy || surveying || !(view.meta && view.meta.continuable) || !hint;
  $('cs-at-end').disabled = surveying || !surveyEnd();
  $('cs-at-start').disabled = surveying || !startMark();
  $('tool-hint').disabled = surveying;
}
function surveyOp(path, body) {
  busy = true; refresh();
  return operation(path, body, () => { busy = false; refresh(); reloadMaps(); });
}
if (ENG) {
  $('btn-survey-start').onclick = () => surveyOp('/api/survey/start', { map_id: $('survey-map-id').value.trim(), description: $('survey-desc').value.trim() });
  $('btn-survey-returned').onclick = () => surveyOp('/api/survey/returned');
  $('btn-survey-save').onclick = () => surveyOp('/api/survey/save', { note: $('survey-note').value.trim() });
  $('btn-survey-abort').onclick = () => surveyOp('/api/survey/abort');
  $('tool-hint').onclick = () => { if (view.tool) { dropTools(); return; } view.tool = 'hint'; $('tool-hint').classList.add('on'); };
  $('cs-at-end').onclick = () => { dropTools(); setHint(surveyEnd(), 'survey end'); };
  $('cs-at-start').onclick = () => { dropTools(); setHint(startMark(), 'start mark'); };
  $('btn-cs-start').onclick = () => {
    if (!hint || busy) return;
    $('survey-msg').textContent = `starting: matching the scan on ${mapId} rev${mapRev}, then loading its pose graph (up to two minutes)…`;
    surveyOp('/api/survey/start', { map_id: mapId, description: $('survey-desc').value.trim(), continue_revision: mapRev,
                                    hint: { x_m: hint.x, y_m: hint.y, yaw_rad: hint.yaw } });
  };
}
const SURVEY_LEVEL = { SAVING: 'warn', RETURN_REVIEW: 'warn' };
const noClosure = '<div class="none">available after "Returned to start"</div>';
function survey(st) {
  const mode = st.mode, m = st.mapping;
  if (!mode) { tiles('survey-state', [['Session', '–', 'no supervisor', 'bad', 'key']]); $('survey-msg').textContent = ''; return; }
  if (mode.mode_name !== 'MAPPING') {
    tiles('survey-state', [
      ['Mode', mode.mode_name, mode.phase || '—', MODE_LEVEL[mode.mode_name], 'key'],
      ['Last saved survey', mode.last_survey_map_id ? `${mode.last_survey_map_id} rev${mode.last_survey_revision}` : '—', 'saved'],
    ]);
    if (!busy) $('survey-msg').textContent = mode.reason || '';
    $('closure').innerHTML = noClosure;
    return;
  }
  if (!m) { tiles('survey-state', [['Session', 'MAPPING', 'waiting for the session coordinator', 'warn', 'key']]); return; }
  tiles('survey-state', [
    ['Session', m.state_name, 'coordinator', SURVEY_LEVEL[m.state_name], 'key'],
    ['Map', m.map_id ? `${m.map_id}${m.revision ? ' rev' + m.revision : ''}` : '—', m.continued_from ? `continues rev${m.continued_from}` : 'id · revision'],
  ]);
  $('survey-msg').textContent = m.message || '';
  if (m.closure_available) {
    tiles('closure', [
      ['dx', num(m.closure_dx_m, 3), 'm', 'warn'],
      ['dy', num(m.closure_dy_m, 3), 'm', 'warn'],
      ['dyaw', num(deg(m.closure_dyaw_rad), 2), '°', 'warn'],
    ]);
  } else $('closure').innerHTML = noClosure;
}

// ---- Jog: preset survey moves (survey_move_node checks the MANUAL authority itself) -------

async function surveyMove(kind, value) {
  let r;
  try { r = await api('/api/survey_move', { kind, value }); } catch (e) { $('sm-status').textContent = 'no response'; return; }
  if (r.status !== 200) $('sm-status').textContent = `refused: ${r.data.message || r.status}`;
}
const dist = () => parseFloat($('sm-dist').value);
$('sm-fwd').onclick = () => surveyMove('straight', dist());
$('sm-rev').onclick = () => surveyMove('straight', -dist());
document.querySelectorAll('#sm-spins button, #sm-spins-cw button').forEach(b => { b.onclick = () => surveyMove('rotate', +b.dataset.deg); });
$('sm-stop').onclick = () => api('/api/survey_move/stop', {}).catch(() => {});
const SM_BUTTONS = () => [...document.querySelectorAll('#sm-spins button, #sm-spins-cw button'), $('sm-fwd'), $('sm-rev')];
function moves(st) {
  const live = surveying && st.mapping && st.mapping.state_name === 'MAPPING';
  const s = st.survey_move;
  const moving = !!s && (s.state_name === 'MOVING' || s.state_name === 'SETTLING');
  SM_BUTTONS().forEach(b => { b.disabled = !live || moving; });
  $('sm-stop').disabled = !(s && s.state_name === 'MOVING');
  const el = $('sm-status');
  el.classList.remove('bad', 'ok');
  if (!live) { el.textContent = 'available while surveying'; return; }
  // the node publishes at 5 Hz: a state older than 2 s is a helper that is not running
  if (s && s.age_s != null && s.age_s > 2.0) {
    SM_BUTTONS().forEach(b => { b.disabled = true; });
    el.textContent = 'move helper not running (it restarts by itself; if not, restart the survey)';
    el.classList.add('bad');
    return;
  }
  if (!s || s.state_name === 'IDLE') { el.textContent = 'ready'; return; }
  const unit = s.kind === 'rotate' ? '°' : ' m';
  const prog = s.kind === 'rotate' ? num(deg(s.progress), 1) : num(s.progress, 2);
  if (s.state_name === 'MOVING') el.textContent = `${s.label}: ${prog}${unit}`;
  else if (s.state_name === 'SETTLING') el.textContent = `${s.label}: stopped at ${prog}${unit}, checking the map…`;
  else if (s.state_name === 'ABORTED') { el.textContent = `${s.label}: stopped at ${prog}${unit} (${s.reason})`; el.classList.add('bad'); }
  else { el.textContent = `${s.label}: done at ${prog}${unit}. ${s.reason}`; el.classList.add(s.check_done && !s.check_ok ? 'bad' : 'ok'); }
}
jogpad($('jog-mp'), { compact: true });

// ---- state -------------------------------------------------------------------------------

onState(st => {
  setSurveying(!!(st.mode && st.mode.mode_name === 'MAPPING'));
  position(st);
  if (ENG) survey(st);
  moves(st);
  refresh();
});

// The map list: the AMCL map if one runs, else what was shown, else the newest revision.
async function reloadMaps() {
  const keep = $('mp-map').value;
  await fillMapSelect($('mp-map'));
  const opts = Array.from($('mp-map').options).map(o => o.value);
  if (!opts.length) { $('mp-hint').textContent = 'no saved maps yet: start a survey (Survey tab)'; return; }
  const lm = lastState && lastState.loc_map, active = lm ? `${lm.map_id}/${lm.map_revision}` : null;
  const pick = opts.includes(keep) ? keep : (active && opts.includes(active) ? active : opts[opts.length - 1]);
  $('mp-map').value = pick;
  if (pick !== keep) await showSaved(pick);
}
hintText();
reloadMaps();
