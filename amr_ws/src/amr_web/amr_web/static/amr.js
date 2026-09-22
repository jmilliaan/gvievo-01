// Shared helpers: JSON requests, a log line, the 2 Hz state poll every page uses,
// the telemetry rail, tile rendering, and the asynchronous-operation helper
// (unified plan §6.2: accepted != completed).
const REQUEST_TIMEOUT_MS = 8000;  // a hung request must not hang a page (Q11); it rejects like a network error
async function request(path, method, body) {
  const ctl = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), REQUEST_TIMEOUT_MS) : null;
  let r;
  try {
    r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
                            body: body === undefined ? undefined : JSON.stringify(body), signal: ctl ? ctl.signal : undefined });
  } finally { if (timer) clearTimeout(timer); }
  let data = null;
  try { data = await r.json(); } catch (e) { data = { ok: false, message: r.statusText }; }
  if (!r.ok && data && data.message) log(data.message, 'bad');
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
// Number formatting: fixed decimals, tabular in CSS; "–" for anything missing or nonfinite.
const num = (v, dp) => (typeof v === 'number' && isFinite(v)) ? v.toFixed(dp) : '–';
const yesno = v => v === undefined || v === null ? '–' : (v ? 'YES' : 'NO');

function pill(id, text, cls) { const e = document.getElementById(id); if (!e) return; e.textContent = text; e.className = 'pill ' + (cls || ''); }
// One telemetry tile: <div class="tel"><span>label</span><b>value</b><i>note</i></div>.
function tile(id, value, note, level, stale) {
  const e = typeof id === 'string' ? document.getElementById(id) : id; if (!e) return;
  e.querySelector('b').textContent = value;
  e.querySelector('i').textContent = note || '—';
  e.classList.toggle('warn', level === 'warn');
  e.classList.toggle('bad', level === 'bad');
  e.classList.toggle('stale', !!stale);
}
// A row of tiles into a container: rows = [[label, value, unit, level, extraClass], ...].
function tiles(container, rows) {
  const e = typeof container === 'string' ? document.getElementById(container) : container; if (!e) return;
  e.innerHTML = rows.map(([label, value, unit, level, extra]) =>
    `<div class="tel ${level || ''} ${extra || ''}"><span>${esc(label)}</span><b>${esc(value)}</b><i>${esc(unit || '—')}</i></div>`).join('');
}

const stateListeners = [];
function onState(fn) { stateListeners.push(fn); }
let lastState = null;
const MODE_LEVEL = { STARTING: 'warn', TRANSITIONING: 'warn', FAULT: 'bad', STOPPING: 'bad' };
const LOC_LEVEL = { CHECKING: 'warn', LOST: 'bad' };
const RUN_LEVEL = { BLOCKED: 'warn', PAUSED: 'warn', FAULT: 'bad' };
const FRESH_S = 0.5;  // panel / drives / mux samples older than this are not current

function rail(st) {
  const m = st.mode;
  tile('tel-mode', m ? m.mode_name : '–', m ? (m.phase || '—') : 'no supervisor', m ? MODE_LEVEL[m.mode_name] : 'bad');
  const p = st.panel;
  if (!p) tile('tel-selector', '–', 'no panel image', 'bad');
  else if (p.age_s > FRESH_S) tile('tel-selector', 'STALE', `${num(p.age_s, 1)} s old`, 'bad');
  else if (!p.valid) tile('tel-selector', 'INVALID', `${num(p.age_s, 2)} s`, 'bad');
  else tile('tel-selector', p.mode_auto ? 'AUTO' : 'MANUAL', `${num(p.age_s, 2)} s`);
  const d = st.drives;
  if (!d) tile('tel-drives', '–', 'no drive status', 'bad');
  else if (d.age_s > FRESH_S) tile('tel-drives', 'STALE', `${num(d.age_s, 1)} s old`, 'bad');
  // both drives in the same state is the normal case: say it once, the rail row is one line
  else tile('tel-drives', d.operational ? 'ARMED' : 'OFF', d.left === d.right ? (d.left || '?') : `${d.left || '?'} · ${d.right || '?'}`, d.operational ? '' : 'warn');
  const mx = st.mux, mxStale = !mx || mx.age_s > FRESH_S;
  tile('tel-source', mx ? mx.source : '–', mx ? (mx.inhibited ? 'inhibited' : '—') : 'no mux state', mx && mx.inhibited ? 'warn' : '', mxStale);
  tile('tel-wheels', mx ? `${num(mx.left_rad_s, 2)} / ${num(mx.right_rad_s, 2)}` : '–', 'rad/s · L / R', '', mxStale);
  const l = st.localization;
  tile('tel-loc', l ? l.state_name : '–', st.localization_stale ? 'stale (replaced layer)' : (l ? '—' : 'no layer'),
       l ? LOC_LEVEL[l.state_name] : '', st.localization_stale);
  const r = st.run;
  tile('tel-run', r ? r.state_name : '–', st.run_stale ? 'stale (replaced layer)' : (r ? (r.step_id || '—') : 'no executor'),
       r ? RUN_LEVEL[r.state_name] : '', st.run_stale);
  tile('tel-gen', m ? String(m.generation) : '–', st.lease ? 'lease' : 'no lease', st.lease ? '' : 'warn');
}
function railStale(on) { const e = document.getElementById('telemetry'); if (e) e.classList.toggle('stale', on); }

// One alarms poll for every page (amr_web/alarms.py decides; nothing is re-derived
// client-side). Pages register with onAlarms(); the rail always shows the top row.
const alarmListeners = [];
function onAlarms(fn) { alarmListeners.push(fn); }
async function pollAlarms() {
  try {
    const { status, data } = await apiGet('/api/alarms');
    if (status === 200) {
      const top = (data.alarms || [])[0];
      const el = document.getElementById('rail-alarm');
      if (el) {
        el.hidden = !top;
        if (top) {
          el.className = 'rail-alarm ' + (top.level === 'error' ? 'bad' : top.level === 'warn' ? 'warn' : '');
          el.innerHTML = `<b>${esc(top.title)}</b><i>${esc(top.action)}</i>`;
        }
      }
      alarmListeners.forEach(fn => fn(data));
    }
  } catch (e) { /* the state poll already reports the disconnection */ }
  setTimeout(pollAlarms, 1000);
}
pollAlarms();

async function poll() {
  try {
    const { status, data } = await apiGet('/api/state');
    if (status === 200) {
      lastState = data;
      pill('pill-link', 'connected', 'ok');
      railStale(false);
      rail(data);
      stateListeners.forEach(fn => fn(data));
    } else { pill('pill-link', 'error ' + status, 'bad'); railStale(true); }
  } catch (e) { pill('pill-link', 'disconnected', 'bad'); railStale(true); }
  setTimeout(poll, 500);
}
poll();

// Wi-Fi header readout: a comfort indicator for whoever holds the tablet, not an authority.
async function pollWifi() {
  const el = document.getElementById('wifi'), txt = document.getElementById('wifi-text');
  if (!el) return;
  let w = null;
  try { const { status, data } = await apiGet('/api/wifi'); if (status === 200) w = data; } catch (e) { /* offline */ }
  const bars = w ? w.bars : 0;
  el.querySelectorAll('.bars b').forEach((b, i) => b.classList.toggle('on', i < bars));
  el.className = 'wifi ' + (!w || !w.connected ? 'bad' : bars >= 3 ? 'ok' : bars >= 2 ? '' : 'warn');
  txt.textContent = !w ? '–' : !w.connected ? `${w.iface} no link` : `${w.ssid || w.iface} ${Math.round(w.dbm)} dBm`;
  setTimeout(pollWifi, 2000);
}
pollWifi();

// Internet as the ROBOT sees it (the server probes; the tablet's own link says nothing about
// it). 0.25 Hz: the server caches its probe for 4 s anyway. Informational only.
async function pollNet() {
  const el = document.getElementById('net');
  if (!el) return;
  let n = null;
  try { const { status, data } = await apiGet('/api/internet'); if (status === 200) n = data; } catch (e) { /* offline */ }
  el.className = 'net ' + (!n || n.online == null ? '' : n.online ? 'ok' : 'bad');
  el.title = !n ? 'Internet: robot not reachable'
    : n.online == null ? 'Internet: checking…'
    : n.online ? `Internet: online (${n.via}, ${n.rtt_ms} ms) - rechecked every 4 s` : 'Internet: offline - rechecked every 4 s';
  setTimeout(pollNet, 4000);
}
pollNet();

// Submit an asynchronous supervisor operation and follow it to a terminal status.
// A refresh/reconnect recovers progress through /api/operations/<id>; nothing is resubmitted.
// onDone is called EXACTLY once on every path - success, refusal, network failure, timeout -
// so a page's busy state always unwinds (review Q11). A request that never got a response
// may still have executed on the robot; it is not resubmitted, the outcome is "unknown".
async function operation(path, body, onDone) {
  const rid = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
  let status, data;
  try { ({ status, data } = await api(path, Object.assign({ request_id: rid }, body || {}))); }
  catch (e) { log(`${path}: no response (outcome unknown; check the state before retrying)`, 'bad'); if (onDone) onDone(null); return null; }
  if (status !== 202) { log(data.message || `refused (${status})`, 'bad'); if (onDone) onDone(null); return null; }
  log(`accepted: ${data.message} (operation ${data.operation_id})`);
  return followOperation(data.operation_id, onDone);
}
async function followOperation(id, onDone) {
  const deadline = Date.now() + 300000;
  let gap = 500;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, gap));
    let status, data;
    try { ({ status, data } = await apiGet(`/api/operations/${id}`)); }
    catch (e) { gap = Math.min(gap * 2, 4000); continue; }  // offline: back off, keep following the same id
    gap = 500;
    if (status !== 200) continue;
    if (data.status_name !== 'PENDING') {
      log(`operation ${id}: ${data.status_name}${data.message ? ' — ' + data.message : ''}`, data.status_name === 'SUCCEEDED' ? '' : 'bad');
      if (onDone) onDone(data);
      return data;
    }
    if (data.phase) tile('tel-mode', '…', data.phase, 'warn');
  }
  log(`operation ${id}: still pending after 5 min (outcome unknown)`, 'bad');
  if (onDone) onDone(null);
  return null;
}

// Page error boundary (plan phase 3.4): a bug in a page script used to leave buttons
// silently dead. Now it says so, keeps the rail polling, and gives the operator a
// reference to read out. Reported to the server so it lands in the event log too.
(function () {
  let reported = false;
  function show(what) {
    const el = document.getElementById('page-error');
    if (!el) return;
    el.hidden = false;
    el.textContent = `Page error — reload this page. (${what})`;
    if (!reported) {
      reported = true;  // one report per page load: a loop of errors must not flood the log
      try { api('/api/page-error', { where: location.pathname, what: String(what).slice(0, 300) }); } catch (e) { /* offline */ }
    }
  }
  window.addEventListener('error', e => show(e.message || 'script error'));
  window.addEventListener('unhandledrejection', e => show((e.reason && e.reason.message) || 'request failed'));
})();

// Role switch (amr_web/role.py): operator <-> engineer. The PIN is typed here and
// checked on the server; it is a mistake guard, not security.
(function () {
  const btn = document.getElementById('role-btn');
  if (!btn) return;
  btn.onclick = async () => {
    if (btn.dataset.role === 'engineer') {
      await api('/api/role', { role: 'operator' });
      location.href = '/home';
      return;
    }
    const pin = prompt('Engineer PIN');
    if (!pin) return;
    const { status, data } = await api('/api/role', { role: 'engineer', pin });
    if (status === 200) location.href = '/status';
    else log(data.message || 'wrong PIN', 'bad');
  };
})();

// Display size knob (amr.css "one layout, three sizes"): s -> m -> l -> s. Stored per
// device; base.html applies the stored value before first paint. The canvases size
// themselves from their box, so a resize event makes them follow the new scale.
(function () {
  const btn = document.getElementById('ui-size');
  if (!btn) return;
  const NEXT = { s: 'm', m: 'l', l: 's' };
  const show = () => { btn.textContent = { s: 'Aa', m: 'Aa+', l: 'Aa++' }[document.documentElement.dataset.ui] || 'Aa'; };
  btn.onclick = () => {
    const u = NEXT[document.documentElement.dataset.ui] || 's';
    document.documentElement.dataset.ui = u;
    try { localStorage.setItem('amr.ui', u); } catch (e) { /* storage blocked: this page only */ }
    show();
    window.dispatchEvent(new Event('resize'));
  };
  show();
})();

// In-page tabs: <div class="tabs" id=X><button class="tab" data-tab="a">…</button></div>
// followed by sibling <div class="tabpane" data-tab="a"> panes. Presentation only.
function tabs(id) {
  const bar = document.getElementById(id); if (!bar) return;
  const panes = [...bar.parentElement.querySelectorAll('.tabpane')];
  const pick = name => {
    bar.querySelectorAll('.tab').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    panes.forEach(p => { p.hidden = p.dataset.tab !== name; });
  };
  bar.querySelectorAll('.tab').forEach(b => { b.onclick = () => pick(b.dataset.tab); });
  const on = bar.querySelector('.tab.on') || bar.querySelector('.tab');
  if (on) pick(on.dataset.tab);
}
