// Alarms page: what is wrong now, and the record of what was wrong before.
//
// Read-only, and pointedly so: there is no "acknowledge" and no "clear". A
// latched fault is cleared at the panel with Reset, by somebody who can see the
// vehicle. A web button that silences an alarm is a web button that silences an
// alarm for a person standing somewhere else.
//
// This page does NOT set window.CLAIM_HEARTBEAT, so leaving it open on a wall
// display cannot hold an auto run alive. See api_state() in server.py.

// info / warn / error map to white, orange, red. The colour is carried by a
// left bar and the label, never by the row's background alone - a fill-only
// scheme is unreadable to a good fraction of operators and vanishes entirely
// in a photograph of the screen.
const LEVEL_CLASS = {info: 'lv-info', warn: 'lv-warn', error: 'lv-error'};

let entries = [];          // newest first
let seq = 0;
let standingSeq = null;    // last /api/state snapshot, for the standing list

const el = (id) => document.getElementById(id);
const stamp = (t) => new Date(t * 1000).toLocaleTimeString('en-GB');

// ---- standing ------------------------------------------------------------
// Live conditions, rebuilt every poll. Deliberately separate from the log: the
// log says a thing HAPPENED, this says it is STILL TRUE, and an operator
// reading a stale "driver silent" line from four minutes ago as a current fact
// is exactly the confusion worth spending a section on.

function renderStanding(s) {
  const box = el('al-standing');
  if (!box) return;
  const rows = [];

  const p = s.panel || {};
  if (p.fault) {
    rows.push(['error', 'Latched fault', p.fault + ' — clear with panel Reset']);
  }

  const hw = s.health || {};
  if (hw.system_error) rows.push(['error', 'Critical device lost', hw.system_detail]);
  if (hw.sensor_error) rows.push(['warn', 'Sensor lost', hw.sensor_detail
                                  + ' — auto unavailable, manual unaffected']);

  const b = s.battery || {};
  if (b.state === 'trip') rows.push(['error', 'Battery', `${b.volts} V`]);
  else if (b.state === 'warn') rows.push(['warn', 'Battery', `${b.volts} V`
                                          + (b.warn_low ? ` (low at ${b.warn_low})` : '')]);

  // The lidar, by the same rule the lamps follow: unknown and stale are
  // reportable states, not silence.
  const l = s.lidar;
  if (l && l.enabled) {
    if (l.stale) rows.push(['error', 'Lidar stream', 'stale — zones assumed occupied']);
    else if (l.zones && !l.zones.validated)
      rows.push(['warn', 'Lidar zones', 'byte mapping unvalidated — see /lidar']);
    if (l.gaps) rows.push(['warn', 'Lidar telegrams', `${l.gaps} lost`]);
  }

  const c = s.can || {};
  for (const [node, al] of Object.entries(c.alarms || {})) {
    if (al) rows.push([al.level === 'error' ? 'error' : 'warn',
                       `Node ${node} EMCY`, `${al.hex || ''} ${al.name || ''}`]);
  }
  for (const [node, fl] of Object.entries(c.flags || {})) {
    for (const f of fl || []) {
      if (f.level === 'warn' || f.level === 'error')
        rows.push([f.level, `Node ${node} ${f.name}`, f.note || '']);
    }
  }
  for (const [node, vals] of Object.entries((c.monitor || {}).nodes || {})) {
    for (const v of Object.values(vals)) {
      if (v.state === 'trip' || v.state === 'warn')
        rows.push([v.state === 'trip' ? 'error' : 'warn',
                   `Node ${node} ${v.label}`, `${v.value}${v.unit}`]);
    }
  }

  if (!rows.length) {
    box.innerHTML = '<div class="mon-none">nothing outstanding</div>';
    return;
  }
  // Worst first. An operator reads the top of a list.
  const rank = {error: 0, warn: 1, info: 2};
  rows.sort((a, b2) => rank[a[0]] - rank[b2[0]]);
  box.innerHTML = rows.map(([lv, what, detail]) =>
    `<div class="al-row ${LEVEL_CLASS[lv]}">`
    + `<span class="al-lv">${lv}</span>`
    + `<span class="al-what"></span><span class="al-detail"></span></div>`)
    .join('');
  // Text set through textContent, never interpolated into the HTML above: an
  // event message can carry anything an exception's str() produced.
  [...box.querySelectorAll('.al-row')].forEach((row, i) => {
    row.querySelector('.al-what').textContent = rows[i][1];
    row.querySelector('.al-detail').textContent = rows[i][2] || '';
  });
}

// ---- the log -------------------------------------------------------------

function renderLog() {
  const box = el('al-log');
  if (!box) return;
  const showInfo = el('f-info').checked;
  const showWarn = el('f-warn').checked;
  const shown = entries.filter(e => e.level === 'error'
                               || (e.level === 'warn' && showWarn)
                               || (e.level === 'info' && showInfo));

  const counts = entries.reduce((a, e) => (a[e.level] = (a[e.level] || 0) + 1, a), {});
  el('al-count').textContent =
    `${entries.length} held · ${counts.error || 0} error · `
    + `${counts.warn || 0} warn · ${counts.info || 0} info`;

  if (!shown.length) {
    box.innerHTML = '<div class="mon-none">nothing to show</div>';
    return;
  }
  box.innerHTML = shown.map(e =>
    `<div class="al-row ${LEVEL_CLASS[e.level] || 'lv-info'}">`
    + `<span class="al-time"></span><span class="al-lv">${e.level}</span>`
    + `<span class="al-msg"></span></div>`).join('');
  [...box.querySelectorAll('.al-row')].forEach((row, i) => {
    row.querySelector('.al-time').textContent = stamp(shown[i].t);
    row.querySelector('.al-msg').textContent = shown[i].msg;
  });
}

async function syncLog(latest) {
  if (latest === undefined || latest === null || latest <= seq) return;
  try {
    const r = await apiGet(`/api/events?since=${seq}`);
    // Newest first, and bounded by what the server retains rather than growing
    // without limit in a tab left open for a week.
    entries = r.events.slice().reverse().concat(entries).slice(0, 400);
    seq = r.seq;
    renderLog();
  } catch (err) {
    /* retried on the next poll */
  }
}

for (const id of ['f-info', 'f-warn']) {
  const c = el(id);
  if (c) c.addEventListener('change', renderLog);
}

onState(s => {
  renderStanding(s);
  syncLog(s.event_seq);
});

// Pull the whole ring once on load - seq starts at 0, so the first sync gets
// everything the controller still holds rather than only what happens next.
syncLog(Infinity);
