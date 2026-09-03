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
    f.style.color = weak ? 'var(--hazard-ink)' : '';
  } else {
    min.textContent = 'digits';
    f.style.color = '';
  }
}

// ---- RFID station tags ----------------------------------------------------
// Lives here rather than in auto.js for the same reason renderSensor does: both
// pages show it. Auto needs the standing junction order; MANUAL needs the tag
// itself, because reading a tag's four-hex value means jogging the vehicle over
// it by hand, and that is done on the page with the arrows.
//
// Every lookup is guarded, so a page showing three tiles and a page showing four
// run the same code. No-ops entirely on a page with no #r-tag.
//
// The reader is on its own thread; this only ever renders what it published.
function showRfid(r, b) {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  if (!r || !document.getElementById('r-tag')) return;
  // last_tag, not just tag: the live value clears as soon as the vehicle rolls
  // off the tag, which is precisely when somebody is looking down to write the
  // number on a piece of paper.
  set('r-tag', r.tag || (r.last_tag ? r.last_tag : '–'));
  set('r-age', r.tag_age_s === null || r.tag_age_s === undefined
               ? 'no tag yet' : r.tag_age_s.toFixed(1) + ' s ago');
  set('r-count', r.tags_seen);

  // The standing junction order. `straight` is the resting state, not a
  // fault, so only a live order or an unhonoured one is coloured.
  b = b || {};
  set('r-branch', b.intent || 'straight');
  set('r-branch-by',
      b.unhonoured ? 'side not in this diverter'
      : b.set_by ? 'tag ' + b.set_by
      : b.junctions ? b.junctions + ' junction(s) configured'
      : 'no junctions configured');
  const br = document.getElementById('r-branch');
  if (br) br.style.color = b.unhonoured ? 'var(--stop)'
                         : (b.intent && b.intent !== 'straight') ? 'var(--hazard-ink)' : '';

  // Three states worth distinguishing, because they need different actions:
  // disabled (nothing to do), carrier down (physical), connected but silent
  // (reader wedged, or the protocol is still wrong).
  const link = document.getElementById('r-link');
  if (!link) return;
  let text, colour;
  if (!r.enabled)            { text = 'off';      colour = ''; }
  else if (r.carrier === false) { text = 'NO CABLE'; colour = 'var(--stop)'; }
  else if (!r.connected)     { text = 'down';     colour = 'var(--stop)'; }
  else if (!r.comms_ok)      { text = 'silent';   colour = 'var(--hazard-ink)'; }
  else                       { text = 'ok';       colour = ''; }
  link.textContent = text;
  link.style.color = colour;
  set('r-detail', r.silent ? 'silent — check antenna'
                          : (r.identity || r.detail || '—'));
}

// ---- the shared rail ------------------------------------------------------
// Battery, state, alarm and the lidar zones, on every page. Rendered here for
// the same reason the verdicts are COMPUTED on the server: four pages deciding
// separately what counts as an alarm is four chances for one of them to say
// everything is fine while the vehicle is stopped.

function setText(id, v) {
  const el = document.getElementById(id);
  if (el) el.textContent = v;
  return el;
}

// One definition of what a zone lamp is showing, shared by the rail and by the
// full lamps on /lidar. Order matters and is the safety-relevant part: stale
// outranks everything, because a dead stream must never render as "clear"
// whatever the last telegram happened to say. See sec 4 of lidar_brief.md.
function zoneState(z, i) {
  const paths = (z && z.paths) || [];
  if (!z || z.stale)   return {on: true,  text: 'STALE',    cls: 'stale'};
  if (!z.validated)    return {on: true,  text: '?',        cls: 'unknown'};
  if (paths[i] === null || paths[i] === undefined)
                       return {on: true,  text: 'UNREAD',   cls: 'stale'};
  if (paths[i])        return {on: true,  text: 'OCCUPIED', cls: ''};
  return {on: false, text: 'clear', cls: ''};
}

function renderRail(s) {
  // Battery: the lower of the two drives. canmon already applied the profile's
  // thresholds, so the colour comes from its verdict rather than from a second
  // copy of the limits living in the browser.
  const b = s.battery || {};
  const bv = setText('batt', b.volts === null || b.volts === undefined
                             ? '–' : b.volts.toFixed(1));
  if (bv) bv.style.color = b.state === 'trip' ? 'var(--stop)'
                         : b.state === 'warn' ? 'var(--hazard-ink)' : '';
  setText('batt-note', b.warn_low ? `V · low at ${b.warn_low}` : 'V');

  // State. `mode` is what the vehicle is armed AS; armed is whether it is
  // energised at all. Both, because "AUTO" while disarmed is not the same
  // thing as "AUTO" while running and must not read as it.
  const mode = (s.mode || '—').toUpperCase();
  const st = setText('vstate', s.armed ? mode : 'IDLE');
  if (st) st.style.color = s.armed ? 'var(--ok)' : '';
  setText('vstate-note', s.armed
    ? (s.auto_running ? 'armed · RUNNING' : 'armed')
    : (s.mode ? `${mode.toLowerCase()} selected` : 'not armed'));

  // Alarm. One line; the full list is on /alarms.
  const a = s.alarm || {};
  const al = setText('alarm', a.level === 'error' ? 'ALARM'
                            : a.level === 'warn' ? 'WARN' : 'none');
  if (al) al.style.color = a.level === 'error' ? 'var(--stop)'
                         : a.level === 'warn' ? 'var(--hazard-ink)' : '';
  setText('alarm-note', a.detail || 'nothing outstanding');

  // Lidar zones. Hidden entirely when the scanner is not in use - three
  // permanent "?" lamps on a vehicle without one is noise, not information.
  const rail = document.getElementById('zone-rail');
  const l = s.lidar;
  if (!rail) return;
  rail.hidden = !(l && l.enabled);
  if (rail.hidden) return;
  let worst = '';
  for (let i = 0; i < 3; i++) {
    const z = zoneState(l.zones, i);
    const lamp = document.getElementById(`rail-z-${i}`);
    if (!lamp) continue;
    lamp.classList.toggle('on', z.on);
    lamp.classList.toggle('unknown', z.cls === 'unknown');
    lamp.classList.toggle('stale', z.cls === 'stale');
    if (z.cls === 'stale') worst = 'STALE';
    else if (z.cls === 'unknown' && !worst) worst = 'unvalidated';
    else if (z.text === 'OCCUPIED' && worst !== 'STALE') worst = 'OCCUPIED';
  }
  const note = setText('rail-z-note', worst || 'clear');
  if (note) note.style.color = worst === 'STALE' || worst === 'OCCUPIED'
                             ? 'var(--stop)'
                             : worst ? 'var(--hazard-ink)' : '';
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
    work.style.color = lp.work_max_ms > 1.5 * lp.target_ms ? 'var(--hazard-ink)' : '';
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
    frames.style.color = lp.starved > 5 ? 'var(--hazard-ink)' : '';
  }
}

// Every page polls this. A page that is DRIVING the vehicle must also claim the
// auto watchdog, by setting window.CLAIM_HEARTBEAT before this script runs; the
// poll then adds ?hb=1 and the server refreshes the deadline.
//
// Opt-in, not automatic: it used to be unconditional, which meant the monitor
// page open on a second screen would hold an auto run alive after the auto page
// was closed. Forgetting the flag stops the run, which is the safe direction.
const listeners = [];
function onState(fn) { listeners.push(fn); }

async function poll() {
  try {
    const s = await apiGet(window.CLAIM_HEARTBEAT ? '/api/state?hb=1'
                                                  : '/api/state');
    // A device that has stopped answering outranks the bus state in the pill:
    // "socketcan:can0 · ARMED" is true but useless when a driver is gone.
    const hw = s.health || {};
    if (hw.system_error) {
      setPill('DRIVER SILENT · ' + hw.system_detail, 'bad');
    } else {
      setPill(s.connected ? (s.how + (s.armed ? ' · ARMED' : ' · idle'))
                          : (s.error || 'no bus'),
              s.connected ? (s.armed ? 'ok' : '') : 'bad');
    }

    for (const id of ['1', '2']) {
      const n = s.nodes[id];
      // Stale telemetry looks identical to live telemetry, so say so rather
      // than showing the last statusword as though it were current.
      const silent = ((hw.sources || {})['driver:' + id] || {}).ok === false;
      document.getElementById('rpm-' + id).textContent =
        n.rpm === null ? '–' : n.rpm;
      const st = document.getElementById('st-' + id);
      st.textContent = `node ${id} ${n.label}  `
        + (silent ? 'NOT ANSWERING'
           : n.statusword === null ? '—'
           : `0x${n.statusword.toString(16).toUpperCase().padStart(4, '0')} ${n.state}`)
        + (n.error_reg ? `  ERR 0x${n.error_reg.toString(16).padStart(2, '0')}` : '');
      st.className = 'st' + ((silent || n.error_reg || n.fault) ? ' bad' : '');
    }
    setText('setpoint', `${s.target.left} / ${s.target.right}`);
    // Watchdog and loop health live on /monitor only now. Both are guarded,
    // because an unguarded lookup for a tile that moved throws inside poll()
    // and silently freezes EVERY page's telemetry.
    setText('wd', s.armed ? s.watchdog_s.toFixed(1) : '–');
    renderLoopHealth(s.loop);
    renderRail(s);

    // Stop reasons now arrive through the server event log, which survives a
    // reload; logging them here too would just double every line.
    syncEvents(s.event_seq);

    renderSensor(s);
    showRfid(s.rfid, s.branch);
    listeners.forEach(fn => fn(s));
  } catch (e) {
    setPill('server unreachable', 'bad');
  }
}

setInterval(poll, 200);
poll();


// Operator panel state. Shared by /manual and /auto: both need to show that the
// vehicle can be armed and started from the physical buttons, and above all
// that a latched fault is why nothing is happening.
onState(s => {
  const strip = document.getElementById('panel-strip');
  if (!strip) return;
  const p = s.panel || {};
  strip.hidden = !p.enabled;
  if (!p.enabled) return;

  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  // null selector = the DI scan has not produced a trusted image yet, which is
  // not the same as MANUAL and must not be shown as it.
  set('pn-sel', p.selector ? p.selector.toUpperCase() : 'unknown');
  const a = p.last_action;
  set('pn-act', a ? `${a.what} (${a.source})` : '–');

  const f = document.getElementById('pn-fault');
  if (f) {
    f.hidden = !p.fault;
    f.textContent = p.fault ? `FAULT — ${p.fault} · press Reset` : '';
  }
});
