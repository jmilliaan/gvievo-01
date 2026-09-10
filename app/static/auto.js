// Auto page: DISPLAY ONLY. It cannot arm, start or stop anything - the panel
// owns those (Start arms and runs). The PID runs on the bus thread, which is
// the only place with a deterministic tick and direct sensor access.
//
// The page still claims the auto watchdog below, and that is not vestigial: it
// is the browser's half of the two-source liveness rule, and canworker keys the
// watchdog on _run_source so a panel-started run is held up by the DI scan
// instead of by this poll.

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
  e.style.color = p.e_mm === null ? 'var(--hazard-ink)' : '';
  set('p-omega', n1(p.omega_cmd, 3));
  set('p-base', n1(p.v_base, 0));
  set('p-red', `−${n1(p.speed_red, 0)} r/min`);
  set('p-cmd', `${n1(p.n_l, 0)} / ${n1(p.n_r, 0)}`);
  set('p-terms', `${n1(p.p, 2)} / ${n1(p.i, 2)} / ${n1(p.d, 2)}`);
  set('p-guard', p.guard || '—');

  const st = document.getElementById('p-state');
  st.textContent = p.state;
  st.style.color = ['line_lost', 'sensor_lost', 'halted'].includes(p.state)
                 ? 'var(--stop)' : (p.state === 'coast' ? 'var(--hazard-ink)' : '');

  // sat_scale < 1 means the pair was scaled down to fit inside 4000 r/min -
  // the turn ratio is preserved but authority has run out.
  const sat = document.getElementById('p-sat');
  sat.textContent = p.sat_scale < 1 ? `SATURATED x${n1(p.sat_scale, 2)}` : '—';
  sat.style.color = p.sat_scale < 1 ? 'var(--stop)' : '';
}

// showRfid moved to common.js - the manual page shows the tag too, and one copy
// of it in two files is one copy that gets fixed in only one of them.
// A held run is standing still with the START latch still claimed, waiting for
// the tape to stay in view. Without a word on screen that is indistinguishable
// from a vehicle that has simply died.
function showHold(s) {
  const el = document.getElementById('p-guard');
  if (!el) return;
  // Station stops moved to their own tile - see showStation(). What is left
  // here is the unplanned one, which is why it keeps the hazard colour.
  if (s.auto_hold) {
    el.textContent = 'HOLDING — ' + s.auto_hold;
    el.style.color = 'var(--hazard-ink)';
  }
}

// Pure presentation model: route transitions remain exclusively server-owned.
function autoView(s) {
  const r = s.route, d = s.route_display || {}, panel = s.panel || {};
  if (!r) return {status: 'LIVE STATE UNAVAILABLE', point: '--', context: 'Route state unavailable'};
  let status = 'STOPPED', point = `POINT ${r.station}`, context = `Retained stage ${r.station} -> ${r.next_station}`;
  if (r.guard_error) {
    status = 'POSITION CHECK REQUIRED'; point = 'POSITION UNKNOWN'; context = r.guard_error + '; return to point 2 and restart';
  } else if (panel.fault || s.health?.system_error || !s.connected) {
    status = 'FAULT'; context = panel.fault || s.health?.system_detail || 'CAN bus unavailable';
  } else if (s.mode === 'manual') {
    status = 'MANUAL';
  } else if (s.auto_hold || s.eto_hold) {
    status = 'HOLD'; context = s.auto_hold || s.eto_hold;
  } else if (panel.starting_in !== null && panel.starting_in !== undefined) {
    status = `STARTING - ${n1(panel.starting_in, 1)} s`;
  } else if (r.initial_assumption && r.parked) {
    status = 'INITIAL POSITION ASSUMED'; context = 'Point 2 assumed at startup; physical Start begins the route';
  } else if (!s.armed) {
    status = 'DISARMED';
  } else if (s.auto_running && r.parked) {
    status = d.stopped === true ? 'WAITING FOR START' : d.stopped === false ? 'STOPPING' : 'STOP STATUS UNKNOWN';
    context = `${d.stopped === true ? 'At' : 'Station tag accepted at'} point ${r.station}`;
  } else if (s.auto_running) {
    status = 'TRAVELLING'; point = `TO POINT ${r.next_station}`; context = `Last route station ${r.station}; leg ${r.station} -> ${r.next_station}`;
  }
  return {status, point, context};
}

// Four states worth distinguishing because they need different actions:
// disabled, carrier down (physical), connected but silent (reader wedged), ok.
// comms_ok alone decides whether a shown tag may be called live; the rest only
// names WHICH failure it is, so a partial snapshot cannot mislabel a live read.
function readerHealth(r) {
  r = r || {};
  if (r.comms_ok) return {link: 'ok', live: true, summary: 'Reader connected'};
  const stale = ' - retained value is historical';
  if (r.enabled === false) return {link: 'off', live: false, summary: 'Reader disabled'};
  if (r.carrier === false) return {link: 'NO CABLE', live: false, summary: 'Reader cable disconnected' + stale};
  if (r.connected === false) return {link: 'down', live: false, summary: 'Reader link down' + stale};
  return {link: 'silent', live: false, summary: 'Reader connected but silent' + stale};
}

let autoLastUpdate = null;
function staleAuto() {
  document.getElementById('auto-status').textContent = 'LIVE STATE UNAVAILABLE';
  document.querySelector('.auto-summary').classList.add('is-stale');
  document.getElementById('auto-tag-label').textContent = 'LAST RECEIVED - STALE';
  document.getElementById('auto-context').textContent = 'Last received route values below are stale';
  document.getElementById('auto-point').textContent = 'LIVE POSITION UNKNOWN';
}
function showStation(s) {
  const r = s.route;
  if (!r) { staleAuto(); return; }
  autoLastUpdate = performance.now();
  const text = (id, value) => { document.getElementById(id).textContent = value; };
  const v = autoView(s), d = s.route_display || {}, tag = s.rfid || {};
  document.querySelector('.auto-summary').classList.remove('is-stale');
  document.querySelector('.auto-summary').dataset.status = v.status;
  text('auto-status', v.status); text('auto-point', v.point); text('auto-context', v.context);
  text('auto-direction', r.travel_direction.toUpperCase());
  text('auto-next-direction', r.parked ? `Next departure: ${(d.next_departure_direction || '--').toUpperCase()} to point ${r.next_station}` : 'Logical route direction');
  text('auto-tag', tag.last_tag || '--');
  const reader = readerHealth(tag);
  text('auto-tag-label', reader.live && tag.tag ? 'RECENT READ' : 'LAST READ');
  text('auto-tag-age', tag.tag_age_s == null ? 'No tag received' : `${n1(tag.tag_age_s, 1)} s ago`);
  text('auto-reader', reader.summary);
  text('auto-lap', `Completed laps: ${r.laps}`);
  const sequence = document.getElementById('auto-sequence');
  sequence.replaceChildren();
  const ids = d.sequence || [];
  [...ids, ...(ids.length ? [ids[0]] : [])].forEach((id, index) => {
    const item = document.createElement('li');
    const last = index === ids.length;
    let label = `POINT ${id}`;
    if (last) label += ' (RETURN)';
    if (!last && id === r.station) label += r.parked ? (v.status === 'WAITING FOR START' ? ' - WAITING' : ' - ROUTE STAGE') : ' - FROM';
    if (id === r.next_station && (r.next_station !== ids[0] || last)) label += ' - NEXT';
    item.textContent = label;
    if (!last && id === r.station) item.className = 'current';
    if (id === r.next_station && (r.next_station !== ids[0] || last)) item.classList.add('next');
    sequence.appendChild(item);
  });
  const e = d.last_encounter;
  text('auto-encounter', e ? `Processed #${e.sequence}: ${e.tag} - ${e.action}${e.station ? ' at point ' + e.station : ''}${e.reason ? ': ' + e.reason : ''} (${n1(e.age_s, 1)} s ago)` : 'No processed route encounter in this reader session');
  text('auto-rfid-count', `${tag.tags_seen ?? '--'} · ${tag.encounter_seq ?? '--'}`);
  text('auto-reader-link', reader.link);
  text('auto-reader-detail', tag.silent ? 'silent — check antenna' : (tag.identity || tag.detail || '—'));
  // The standing junction order survives the summary rewrite: an auto run has
  // one, and hardware acceptance checks it still latches during route holds.
  const b = s.branch || {};
  text('auto-branch', b.intent || 'straight');
  const why = b.unhonoured ? 'side not in this diverter'
            : b.set_by ? 'tag ' + b.set_by
            : b.junctions ? b.junctions + ' junction(s) configured'
            : 'no junctions configured';
  text('auto-branch-by', b.slow ? why + ' · SLOW' : why);
  text('p-speed-mode', s.pid?.speed_mode || 'normal');
  text('p-speed-target', s.pid ? `${n1(s.pid.speed_target_rpm, 0)} r/min reference` : 'Reference unavailable');
  text('p-route-guard', r.guard_error ? 'POSITION CHECK' : (r.guard_enabled ? 'on' : 'off'));
  text('p-route-distance', `${n1(r.distance_estimate_m, 2)} m estimated from departure`);
}

onState(s => { showPid(s.pid); showHold(s); showStation(s); });
window.addEventListener('state-poll-error', staleAuto);
// Presentation freshness only; this timer never refreshes or changes a watchdog.
setInterval(() => { if (autoLastUpdate === null || performance.now() - autoLastUpdate > 1000) staleAuto(); }, 200);
