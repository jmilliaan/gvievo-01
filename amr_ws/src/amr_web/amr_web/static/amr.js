// Shared helpers: JSON requests, a log line, the 2 Hz state poll every page uses,
// and the asynchronous-operation helper (unified plan §6.2: accepted != completed).
async function request(path, method, body) {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
                                body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch (e) { data = { ok: false, message: r.statusText }; }
  if (!r.ok && data && data.message) log(data.message, 'err');
  return { status: r.status, data };
}
// Every value from the robot, a saved file or an operator note goes into innerHTML only
// through esc(): route step ids, survey notes and event text are data, not markup (R30).
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const api = (path, body) => request(path, 'POST', body || {});
const apiGet = (path) => request(path, 'GET');
function log(msg, cls) {
  const el = document.getElementById('log');
  const t = new Date().toLocaleTimeString();
  el.textContent = `${t}  ${msg}\n` + el.textContent.split('\n').slice(0, 60).join('\n');
}
function pill(id, text, cls) { const e = document.getElementById(id); if (!e) return; e.textContent = text; e.className = 'pill ' + (cls || ''); }
const stateListeners = [];
function onState(fn) { stateListeners.push(fn); }
let lastState = null;
const MODE_CLS = { IDLE: 'ok', MAPPING: 'ok', NAVIGATION: 'ok', TRANSITIONING: 'warn', STARTING: 'warn', FAULT: 'err', STOPPING: 'err' };
async function poll() {
  try {
    const { status, data } = await apiGet('/api/state');
    if (status === 200) {
      lastState = data;
      pill('pill-link', 'connected', 'ok');
      const m = data.mode;
      pill('pill-mode', m ? `mode ${m.mode_name}${m.phase ? ' · ' + m.phase : ''}` : 'no supervisor', m ? MODE_CLS[m.mode_name] : 'err');
      const p = data.panel;
      pill('pill-panel', p ? (p.age_s > 0.5 ? 'panel stale' : (p.valid ? (p.mode_auto ? 'selector AUTO' : 'selector MANUAL') : 'panel invalid')) : 'panel —',
           p && p.age_s <= 0.5 && p.valid ? (p.mode_auto ? 'warn' : 'ok') : 'err');
      const d = data.drives;
      pill('pill-drives', d ? (d.age_s > 0.5 ? 'drives stale' : (d.operational ? 'drives armed (zero)' : 'drives de-energised')) : 'drives —',
           d && d.age_s <= 0.5 ? (d.operational ? 'ok' : 'warn') : 'err');
      const l = data.localization;
      pill('pill-loc', 'localisation ' + (l ? l.state_name : (data.localization_stale ? 'stale' : '—')), l ? ({READY:'ok', CHECKING:'warn', LOST:'err'}[l.state_name] || '') : '');
      const r = data.run;
      pill('pill-run', 'run ' + (r ? r.state_name : (data.run_stale ? 'stale' : '—')), r ? ({EXECUTING:'ok', READY:'ok', BLOCKED:'warn', PAUSED:'warn', FAULT:'err'}[r.state_name] || '') : '');
      stateListeners.forEach(fn => fn(data));
    } else pill('pill-link', 'error ' + status, 'err');
  } catch (e) { pill('pill-link', 'disconnected', 'err'); }
  setTimeout(poll, 500);
}
poll();

// Submit an asynchronous supervisor operation and follow it to a terminal status.
// A refresh/reconnect recovers progress through /api/operations/<id>; nothing is resubmitted.
async function operation(path, body, onDone) {
  const rid = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
  const { status, data } = await api(path, Object.assign({ request_id: rid }, body || {}));
  if (status !== 202) { log(data.message || `refused (${status})`, 'err'); if (onDone) onDone(null); return null; }
  log(`accepted: ${data.message} (operation ${data.operation_id})`);
  return followOperation(data.operation_id, onDone);
}
async function followOperation(id, onDone) {
  for (let i = 0; i < 600; i++) {
    await new Promise(r => setTimeout(r, 500));
    const { status, data } = await apiGet(`/api/operations/${id}`);
    if (status !== 200) continue;
    if (data.status_name !== 'PENDING') {
      log(`operation ${id}: ${data.status_name}${data.message ? ' — ' + data.message : ''}`, data.status_name === 'SUCCEEDED' ? '' : 'err');
      if (onDone) onDone(data);
      return data;
    }
    if (data.phase) pill('pill-mode', `mode … ${data.phase}`, 'warn');
  }
  log(`operation ${id}: still pending after 5 min`, 'err');
  return null;
}
