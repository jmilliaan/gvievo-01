// Shared helpers: JSON requests, a log line, and the 2 Hz state poll every page uses.
async function request(path, method, body) {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
                                body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch (e) { data = { ok: false, message: r.statusText }; }
  if (!r.ok && data && data.message) log(data.message, 'err');
  return { status: r.status, data };
}
const api = (path, body) => request(path, 'POST', body || {});
const apiGet = (path) => request(path, 'GET');
function log(msg, cls) {
  const el = document.getElementById('log');
  const t = new Date().toLocaleTimeString();
  el.textContent = `${t}  ${msg}\n` + el.textContent.split('\n').slice(0, 60).join('\n');
}
function pill(id, text, cls) { const e = document.getElementById(id); e.textContent = text; e.className = 'pill ' + (cls || ''); }
const stateListeners = [];
function onState(fn) { stateListeners.push(fn); }
let lastState = null;
async function poll() {
  try {
    const { status, data } = await apiGet('/api/state');
    if (status === 200) {
      lastState = data;
      pill('pill-link', 'connected', 'ok');
      const l = data.localization;
      pill('pill-loc', 'localisation ' + (l ? l.state_name : '—'), l ? ({READY:'ok', CHECKING:'warn', LOST:'err'}[l.state_name] || '') : '');
      const r = data.run;
      pill('pill-run', 'run ' + (r ? r.state_name : '—'), r ? ({EXECUTING:'ok', READY:'ok', BLOCKED:'warn', PAUSED:'warn', FAULT:'err'}[r.state_name] || '') : '');
      stateListeners.forEach(fn => fn(data));
    } else pill('pill-link', 'error ' + status, 'err');
  } catch (e) { pill('pill-link', 'disconnected', 'err'); }
  setTimeout(poll, 500);
}
poll();
