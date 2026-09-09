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

// A station ID distinguishes physical stops that share an RFID value.
function showStation(s) {
  const r = s.route;
  if (!r) return;
  const v = document.getElementById('p-stn');
  const note = document.getElementById('p-stn-note');
  if (v && note) {
    v.textContent = r.station;
    note.textContent = r.parked ? 'AT STATION — press Start' : 'last confirmed station';
  }
  document.getElementById('p-direction').textContent = r.travel_direction.toUpperCase();
  document.getElementById('p-route').textContent = `${r.station} → ${r.next_station} · lap ${r.laps}`;
  document.getElementById('p-speed-mode').textContent = s.pid?.speed_mode || 'normal';
  document.getElementById('p-speed-target').textContent = s.pid
    ? `${n1(s.pid.speed_target_rpm, 0)} r/min reference` : 'r/min reference';
}

onState(s => { showPid(s.pid); showHold(s); showStation(s); });
