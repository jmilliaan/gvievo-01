// Auto page: start/stop the line-following run and display what it is doing.
// No control logic here - the PID runs on the bus thread (canworker), which is
// the only place with a deterministic tick and direct sensor access.

let armed = false, running = false;
const armBtn = document.getElementById('arm');
const runBtn = document.getElementById('run');

armBtn.addEventListener('click', async () => {
  try {
    const r = await api('/api/arm', {mode: 'auto'});
    (r.report || []).forEach(l => log(l));
    log('armed — sensor in Operational, TPDO1 streaming');
  } catch (e) { log('ARM FAILED: ' + e.message); }
});

runBtn.addEventListener('click', async () => {
  try {
    const r = await api('/api/auto/run', {run: !running});
    if (!r.running) { log('stopped — ramping down'); return; }
    log(`running — ${window.AUTO_RPM} r/min` + (r.dry_run ? ' (DRY RUN, 0 to drivers)' : ''));
    if (r.log) log('logging to ' + r.log);
  } catch (e) { log('run: ' + e.message); }
});

document.getElementById('disarm').addEventListener('click', async () => {
  try { await api('/api/disarm'); log('disarmed — motors de-energised'); }
  catch (e) { log('disarm: ' + e.message); }
});

const n1 = (v, d = 1) => (v === null || v === undefined) ? '–' : v.toFixed(d);

function showPid(p) {
  const set = (id, v) => document.getElementById(id).textContent = v;
  if (!p) {
    ['p-err', 'p-omega', 'p-base', 'p-cmd', 'p-terms'].forEach(i => set(i, '–'));
    set('p-state', 'idle'); set('p-guard', '—'); set('p-red', 'r/min');
    set('p-sat', '—');
    return;
  }
  const e = document.getElementById('p-err');
  e.textContent = p.e_mm === null ? 'no track'
                                  : (p.e_mm > 0 ? '+' : '') + n1(p.e_mm);
  e.style.color = p.e_mm === null ? 'var(--warn)' : '';
  set('p-omega', n1(p.omega_cmd, 3));
  set('p-base', n1(p.v_base, 0));
  set('p-red', `−${n1(p.speed_red, 0)} r/min`);
  set('p-cmd', `${n1(p.n_l, 0)} / ${n1(p.n_r, 0)}`);
  set('p-terms', `${n1(p.p, 2)} / ${n1(p.i, 2)} / ${n1(p.d, 2)}`);
  set('p-guard', p.guard || '—');

  const st = document.getElementById('p-state');
  st.textContent = p.state;
  st.style.color = ['line_lost', 'sensor_lost', 'halted'].includes(p.state)
                 ? 'var(--bad)' : (p.state === 'coast' ? 'var(--warn)' : '');

  // sat_scale < 1 means the pair was scaled down to fit inside 4000 r/min -
  // the turn ratio is preserved but authority has run out.
  const sat = document.getElementById('p-sat');
  sat.textContent = p.sat_scale < 1 ? `SATURATED x${n1(p.sat_scale, 2)}` : '—';
  sat.style.color = p.sat_scale < 1 ? 'var(--bad)' : '';
}

// The reader is on its own thread; this only ever renders what it published.
function showRfid(r) {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  if (!r) return;
  set('r-tag', r.tag || (r.last_tag ? r.last_tag : '–'));
  set('r-age', r.tag_age_s === null || r.tag_age_s === undefined
               ? 'no tag yet' : r.tag_age_s.toFixed(1) + ' s ago');
  set('r-count', r.tags_seen);

  // Three states worth distinguishing, because they need different actions:
  // disabled (nothing to do), carrier down (physical), connected but silent
  // (reader wedged, or the protocol is still wrong).
  const link = document.getElementById('r-link');
  if (!link) return;
  let text, colour;
  if (!r.enabled)            { text = 'off';      colour = ''; }
  else if (r.carrier === false) { text = 'NO CABLE'; colour = 'var(--bad)'; }
  else if (!r.connected)     { text = 'down';     colour = 'var(--bad)'; }
  else if (!r.comms_ok)      { text = 'silent';   colour = 'var(--warn)'; }
  else                       { text = 'ok';       colour = ''; }
  link.textContent = text;
  link.style.color = colour;
  set('r-detail', r.silent ? 'silent — check antenna'
                          : (r.identity || r.detail || '—'));
}

onState(s => {
  showRfid(s.rfid);
  armed = s.armed && s.mode === 'auto';
  running = s.auto_running;
  showPid(s.pid);
  runBtn.disabled = !armed;
  runBtn.textContent = running ? 'STOP' : 'START';
  runBtn.classList.toggle('off', running);
  runBtn.classList.toggle('run', !running);
});
