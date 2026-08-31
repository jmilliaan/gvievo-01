// Shared plumbing: API calls, the telemetry poll, and the footer readout.

// The method is explicit, never inferred. An earlier version picked GET when no
// body was passed, which silently turned /api/stop and /api/disarm - both of
// which legitimately take no body - into GETs against POST-only routes. They
// 405'd, and because the stop call swallows its errors, releasing a button
// quietly did nothing and the AGV only stopped when the watchdog expired.
async function request(path, method, body) {
  const opt = {method};
  if (method !== 'GET') {
    opt.headers = {'Content-Type': 'application/json'};
    opt.body = JSON.stringify(body || {});
  }
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
  return data;
}

// Every mutating endpoint is a POST; /api/state and /api/config are the reads.
const api = (path, body) => request(path, 'POST', body);
const apiGet = (path) => request(path, 'GET');

const logEl = document.getElementById('log');
function log(msg, cls) {
  const t = new Date().toLocaleTimeString('en-GB');
  logEl.textContent = `${t}  ${msg}\n` + logEl.textContent;
  logEl.textContent = logEl.textContent.split('\n').slice(0, 40).join('\n');
}

// ---- server event log -----------------------------------------------------
// The vehicle stops itself on line loss, sensor timeout and watchdog, so the
// reason has to outlive a page reload. The server keeps the ring buffer; this
// only mirrors it. /api/state carries the high-water mark, so we fetch the
// events themselves only when we have actually fallen behind.
let eventSeq = 0;
let eventBusy = false;

async function syncEvents(latest) {
  if (eventBusy || latest === undefined || latest === null) return;
  if (latest <= eventSeq) return;
  eventBusy = true;
  try {
    const r = await apiGet(`/api/events?since=${eventSeq}`);
    for (const e of r.events) {
      const t = new Date(e.t * 1000).toLocaleTimeString('en-GB');
      const mark = e.level === 'error' ? '!! ' : (e.level === 'warn' ? ' ! ' : '   ');
      logEl.textContent = `${t}${mark}${e.msg}\n` + logEl.textContent;
    }
    logEl.textContent = logEl.textContent.split('\n').slice(0, 60).join('\n');
    eventSeq = r.seq;
  } catch (err) {
    /* a missed sync is retried on the next poll; never disturb the page */
  } finally {
    eventBusy = false;
  }
}

function setPill(text, cls) {
  const p = document.getElementById('link');
  p.textContent = text;
  p.className = 'pill' + (cls ? ' ' + cls : '');
}

// ---- MLS tape strip -------------------------------------------------------
// Lives here rather than in auto.js because both pages show it: auto to see what
// the PID is reacting to, manual to line the AGV up on the tape before handing
// over. No-ops on any page without a #track element.

const TRACK_HALF_MM = 65;   // MLS sensing width is ~130 mm, so +/-65 mm full scale

function placeLcp(el, track) {
  if (!el) return;
  if (!track) { el.style.display = 'none'; return; }
  const pct = 50 + 50 * Math.max(-1, Math.min(1, track.pos_mm / TRACK_HALF_MM));
  el.style.display = 'block';
  el.style.left = pct + '%';
  el.dataset.mm = (track.pos_mm > 0 ? '+' : '') + track.pos_mm
                  + (track.width !== null ? ` w${track.width}` : '');
}

function renderSensor(s) {
  if (!document.getElementById('track')) return;
  const txt = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };
  const sen = s.sensor;
  const byIndex = {};
  if (sen) for (const t of sen.tracks) byIndex[t.index] = t;
  placeLcp(document.getElementById('lcp1'), byIndex[1]);
  placeLcp(document.getElementById('lcp2'), byIndex[2]);
  placeLcp(document.getElementById('lcp3'), byIndex[3]);

  const empty = document.getElementById('track-empty');
  if (empty) {
    empty.style.display = (sen && sen.has_track) ? 'none' : 'flex';
    // s.armed, not a per-page notion of armed: the sensor now streams on any
    // arm, so "not armed" is the honest reason on both pages.
    empty.textContent = sen ? 'no track'
                            : (s.armed ? 'waiting for TPDO1…' : 'not armed');
  }

  txt('s-nlcp',  sen ? sen.nlcp : '–');
  txt('s-label', sen ? sen.label : '—');
  txt('s-pos', byIndex[2] ? (byIndex[2].pos_mm > 0 ? '+' : '') + byIndex[2].pos_mm : '–');
  txt('s-level', sen ? sen.track_level : '–');
  txt('s-pol',   sen ? sen.polarity : '—');
  txt('s-frames', s.sensor_frames);
  txt('s-age', s.sensor_age_s === null ? '—' : s.sensor_age_s.toFixed(1) + ' s ago');
  txt('s-marker', sen && (sen.marker.intro || sen.marker.code) ? sen.marker.code : '–');

  const f = document.getElementById('s-field');
  const min = document.getElementById('s-min');
  if (!f || !min) return;
  f.textContent = s.field_level === null ? '–' : s.field_level;
  if (s.field_level !== null && s.min_level !== null) {
    const weak = s.field_level < s.min_level;
    min.textContent = weak ? `below min ${s.min_level}` : `min ${s.min_level}`;
    f.style.color = weak ? 'var(--warn)' : '';
  } else {
    min.textContent = 'digits';
    f.style.color = '';
  }
}

// ---- loop health ----------------------------------------------------------
// work = time the bus thread spent doing things; period = the interval it
// actually achieved. Splitting them says whether a late tick is the controller
// or the bus. Amber once the worst tick runs past 1.5x the target period.
function renderLoopHealth(lp) {
  const work = document.getElementById('loop-work');
  if (!work || !lp) return;
  const period = document.getElementById('loop-period');
  const frames = document.getElementById('loop-frames');
  const starved = document.getElementById('loop-starved');

  if (lp.work_avg_ms === null || lp.work_avg_ms === undefined) {
    work.textContent = '–';
    period.textContent = 'ms work';
  } else {
    work.textContent = `${lp.work_avg_ms.toFixed(1)}/${lp.work_max_ms.toFixed(0)}`;
    period.textContent = `ms avg/max · ${lp.target_ms.toFixed(0)} target`;
    work.style.color = lp.work_max_ms > 1.5 * lp.target_ms ? 'var(--warn)' : '';
  }

  if (lp.frames_per_tick === null || lp.frames_per_tick === undefined) {
    frames.textContent = '–';
    starved.textContent = 'per tick';
  } else {
    frames.textContent = lp.frames_per_tick.toFixed(1);
    // A starved tick is one where the loop was armed but no new sensor frame
    // had arrived - the PID would be looking at a frame it already used.
    starved.textContent = lp.starved ? `per tick · ${lp.starved} starved`
                                     : 'per tick';
    frames.style.color = lp.starved > 5 ? 'var(--warn)' : '';
  }
}

// Every page polls this; on the auto page it doubles as the watchdog heartbeat.
const listeners = [];
function onState(fn) { listeners.push(fn); }

async function poll() {
  try {
    const s = await apiGet('/api/state');
    setPill(s.connected ? (s.how + (s.armed ? ' · ARMED' : ' · idle'))
                        : (s.error || 'no bus'),
            s.connected ? (s.armed ? 'ok' : '') : 'bad');

    for (const id of ['1', '2']) {
      const n = s.nodes[id];
      document.getElementById('rpm-' + id).textContent =
        n.rpm === null ? '–' : n.rpm;
      const st = document.getElementById('st-' + id);
      st.textContent = `node ${id} ${n.label}  `
        + (n.statusword === null ? '—'
           : `0x${n.statusword.toString(16).toUpperCase().padStart(4, '0')} ${n.state}`)
        + (n.error_reg ? `  ERR 0x${n.error_reg.toString(16).padStart(2, '0')}` : '');
      st.className = 'st' + ((n.error_reg || n.fault) ? ' bad' : '');
    }
    document.getElementById('setpoint').textContent =
      `${s.target.left} / ${s.target.right}`;
    document.getElementById('wd').textContent =
      s.armed ? s.watchdog_s.toFixed(1) : '–';
    renderLoopHealth(s.loop);

    // Stop reasons now arrive through the server event log, which survives a
    // reload; logging them here too would just double every line.
    syncEvents(s.event_seq);

    renderSensor(s);
    listeners.forEach(fn => fn(s));
  } catch (e) {
    setPill('server unreachable', 'bad');
  }
}

setInterval(poll, 200);
poll();
