// Lidar page: the scan picture, the cut-off path lamps and the stream health.
//
// Read-only by construction. There is no write endpoint to call and this file
// contains no handler that touches the vehicle - the only control on the page
// changes how far out the picture is drawn.
//
// This page does NOT set window.CLAIM_HEARTBEAT, so leaving it open on a second
// screen cannot hold an auto run alive. See api_state() in server.py.
//
// THE RULE THIS FILE EXISTS TO ENFORCE
// ------------------------------------
// lidar_brief.md sec 4: "Absence of data is never 'clear'." Three dark lamps and
// an empty picture are exactly what a healthy scanner looks like when the room
// is clear, and exactly what a dead one looks like too. So staleness does not
// dim this page the way io.js dims the I/O grid - it forces every path lamp ON
// and says so. Latching the last-known-good state is the bug that kills someone.

const cfg = window.LIDAR || {};
const canvas = document.getElementById('scan');
const ctx = canvas.getContext('2d');
const viewSel = document.getElementById('scan-view');

let cloud = null;         // last /api/lidar payload
let viewM = 12;

// THE SCAN IS OFF BY DEFAULT, and every page load starts off again.
//
// Not a preference and deliberately not remembered: decoding 1652 points is
// ~500 us of CPU per poll, and a browser left open on this page overnight would
// spend all night doing it for nobody. Off is also what leaving the page gives
// you for free - navigating away destroys this script, so the poll stops with
// it - and having the toggle default to off means the two behave the same.
//
// The zone lamps and the stream tiles keep updating either way. They ride on
// /api/state, which every page polls regardless, so turning the picture off
// costs no safety-relevant information.
let scanOn = false;

const css = (name) => getComputedStyle(document.body).getPropertyValue(name).trim();

// ---- the picture ----------------------------------------------------------

function resize() {
  // Draw at device resolution: 1652 points on a CSS-scaled canvas turn into a
  // grey smear on any HiDPI screen.
  const dpr = window.devicePixelRatio || 1;
  const box = canvas.getBoundingClientRect();
  const side = Math.max(240, Math.min(box.width, 720));
  canvas.width = Math.round(side * dpr);
  canvas.height = Math.round(side * dpr);
  canvas.style.height = side + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return side;
}

function draw() {
  const side = resize();
  const cx = side / 2, cy = side / 2;
  const pad = 10;
  const scale = (side / 2 - pad) / (viewM * 1000);   // px per mm
  const stale = !cloud || cloud.stale;

  ctx.clearRect(0, 0, side, side);
  ctx.fillStyle = css('--surface');
  ctx.fillRect(0, 0, side, side);

  // Range rings. Drawn even with no data, so an empty picture still reads as a
  // scale drawing rather than as a blank panel.
  const rings = [
    [cfg.protective_m, css('--stop'), `${cfg.protective_m} m stop`],
    [cfg.warning_m, css('--hazard'), `${cfg.warning_m} m warn`],
  ];
  ctx.lineWidth = 1;
  for (const [m, colour, label] of rings) {
    const r = m * 1000 * scale;
    if (r > side / 2) continue;
    ctx.strokeStyle = colour;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = colour;
    ctx.font = '10px ui-monospace, monospace';
    ctx.fillText(label, cx + 4, cy - r - 3);
  }

  // Metre grid, faint, so distances are readable without a ruler.
  ctx.strokeStyle = css('--rule-soft');
  for (let m = 1; m <= viewM; m++) {
    if (m === Math.round(cfg.protective_m) || m === cfg.warning_m) continue;
    const r = m * 1000 * scale;
    if (r > side / 2 - pad) break;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
  }

  // The 0 deg axis, drawn because the bearing convention is NOT yet verified
  // and this is the reference somebody will hold a target against.
  ctx.strokeStyle = css('--ink-3');
  ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx, pad); ctx.stroke();
  ctx.fillStyle = css('--ink-3');
  ctx.font = '10px ui-monospace, monospace';
  ctx.fillText('0°', cx + 4, pad + 10);

  // The vehicle.
  ctx.fillStyle = css('--ink-2');
  ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fill();

  if (!scanOn || !cloud || !cloud.points || cloud.start_angle_deg === null
      || cloud.start_angle_deg === undefined) {
    ctx.fillStyle = css('--ink-3');
    ctx.font = '12px ui-monospace, monospace';
    // "off" and "no data" are different facts and must not share a rendering:
    // one is a switch somebody flipped, the other is a scanner that stopped.
    ctx.fillText(!scanOn ? 'scan off' : (stale ? 'no data' : 'waiting…'),
                 cx + 10, cy - 8);
    return;
  }

  // Bearings are reconstructed here rather than sent per point: 1652 angles
  // would double the payload to say something the geometry already implies.
  const start = cloud.start_angle_deg;
  const res = cloud.resolution_deg * (cloud.step || 1);
  const pts = cloud.points, st = cloud.status || [];
  const noEcho = cloud.no_echo_mm || 40000;
  const dot = side > 480 ? 1.6 : 1.2;

  ctx.fillStyle = stale ? css('--ink-3') : css('--accent-2');
  for (let i = 0; i < pts.length; i++) {
    const d = pts[i];
    // Valid bit clear, no echo, or zero: not a surface. Plotting no-echo
    // returns paints a solid arc at 40 m across an empty room.
    if (!(st[i] & 1) || d <= 0 || d >= noEcho) continue;
    if (d * scale > side / 2 - pad) continue;
    const a = (start + i * res) * Math.PI / 180;
    // 0 deg up, positive clockwise. UNVERIFIED - see the note on the page.
    ctx.fillRect(cx + Math.sin(a) * d * scale - dot / 2,
                 cy - Math.cos(a) * d * scale - dot / 2, dot, dot);
  }
}

// ---- the lamps ------------------------------------------------------------

function paintZones(z) {
  // The state machine itself lives in common.js, shared with the rail on every
  // page. Two copies of "what does a stale zone look like" is one copy that
  // gets the safety-relevant ordering wrong.
  for (let i = 0; i < 3; i++) {
    const lamp = document.getElementById(`z-${i}`);
    const label = document.getElementById(`z-s-${i}`);
    if (!lamp) continue;
    const st = zoneState(z, i);
    lamp.classList.toggle('on', st.on);
    lamp.classList.toggle('unknown', st.cls === 'unknown');
    lamp.classList.toggle('stale', st.cls === 'stale');
    if (label) {
      label.textContent = st.text;
      label.style.color = st.cls === 'unknown' ? 'var(--hazard-ink)'
                        : st.on ? 'var(--stop)' : '';
    }
  }
  const banner = document.getElementById('scan-stale');
  // Only meaningful while the picture is being drawn: a stale banner over a
  // switched-off scan is telling you about a picture that is not there.
  if (banner) banner.hidden = !(scanOn && (!z || z.stale));
}

// ---- telemetry ------------------------------------------------------------

onState(s => {
  const l = s.lidar;
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  if (!l) return;

  paintZones(l.zones);

  // Same three states worth telling apart as the I/O page: disabled, never
  // connected, and connected-but-stale.
  let text, colour;
  if (!l.enabled)          { text = 'off';    colour = ''; }
  else if (!l.connected)   { text = 'down';   colour = 'var(--stop)'; }
  else if (!l.comms_ok)    { text = 'STALE';  colour = 'var(--stop)'; }
  else                     { text = 'ok';     colour = ''; }
  const link = document.getElementById('l-link');
  if (link) { link.textContent = text; link.style.color = colour; }
  set('l-detail', l.detail || '—');

  set('l-rate', l.rate_hz ? l.rate_hz.toFixed(1) : '–');
  set('l-age', l.rx_age_s === null || l.rx_age_s === undefined
               ? 'never' : (l.rx_age_s * 1000).toFixed(0) + ' ms ago');
  set('l-count', l.telegrams);

  // Gaps are dropped datagrams - a network or CPU-load problem that is
  // otherwise completely invisible. Amber, not red: the stream recovered.
  const gaps = document.getElementById('l-gaps');
  if (gaps) {
    gaps.textContent = `${l.gaps || 0} gap · ${l.dropped || 0} partial`;
    gaps.style.color = (l.gaps || l.dropped) ? 'var(--hazard-ink)' : '';
  }

  set('l-beams', l.beams || '–');
  const d = l.derived;
  set('l-span', d ? `${d.start_angle_deg.toFixed(1)}° … `
                  + `${(d.start_angle_deg + l.beams * d.resolution_deg).toFixed(1)}°`
                  : '—');
});

// ---- the cloud, on its own poll -------------------------------------------
// Separate from /api/state and 5 Hz rather than 34: the scan is ~2 KB of JSON
// and this is a picture for a human, not a control input. Follows monitor.js,
// which polls /api/can on its own interval for the same reason.

async function pollCloud() {
  if (!scanOn) return;          // no request at all, not a discarded one
  try {
    cloud = await apiGet('/api/lidar');
  } catch (e) {
    cloud = null;               // never keep drawing a scan we can no longer fetch
  }
  draw();
}

function setScan(on) {
  scanOn = !!on;
  cloud = null;                 // never show a frozen scan as though it were live
  const btn = document.getElementById('scan-toggle');
  if (btn) {
    btn.textContent = scanOn ? 'Stop scan' : 'Start scan';
    btn.classList.toggle('on', scanOn);
  }
  const off = document.getElementById('scan-off');
  if (off) off.hidden = scanOn;
  draw();
  if (scanOn) pollCloud();      // first frame immediately, not in 200 ms
}

// Guarded, because an unguarded listener on a missing element throws at load
// and takes the whole file with it - including pollCloud, leaving a page that
// looks alive and shows a scan frozen at whatever arrived first.
if (viewSel) {
  viewSel.addEventListener('change', () => {
    viewM = parseFloat(viewSel.value) || 12;
    draw();
  });
}
window.addEventListener('resize', draw);

const toggleBtn = document.getElementById('scan-toggle');
if (toggleBtn) toggleBtn.addEventListener('click', () => setScan(!scanOn));

// A backgrounded tab is nobody looking at the picture. Browsers throttle timers
// there anyway, but this makes it explicit and immediate.
document.addEventListener('visibilitychange', () => {
  if (document.hidden && scanOn) setScan(false);
});

setInterval(pollCloud, 200);
setScan(false);
