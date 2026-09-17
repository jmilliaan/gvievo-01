// Shared jog component (unified plan §6.3). Mount with jogpad(container).
//
// Held, not latched: a physical press (pointer down on a pad button, or a key
// down) obtains a server jog session, then refreshes it every 100 ms while the
// input is held. Each refresh carries the single-use ticket the server issued
// with the previous one; releasing the input releases the session BEFORE a zero
// is sent, and anything that could mean "the operator is no longer holding
// this" - blur, pagehide, hidden tab, pointer cancel, a focused text field -
// releases too. There is no timer on the server: if the refreshes stop, the
// command dies 0.2 s later on the robot regardless of what this page does.
function jogpad(root) {
  const owner = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random())).slice(0, 32);
  const speeds = [0.10, 0.20, 0.30];
  root.innerHTML = `
    <div class="jog">
      <div class="jog-grid">
        <button data-dir="fl">↖</button><button data-dir="f">▲</button><button data-dir="fr">↗</button>
        <button data-dir="l">◀</button><button data-dir="stop" class="danger">STOP</button><button data-dir="r">▶</button>
        <button data-dir="bl">↙</button><button data-dir="b">▼</button><button data-dir="br">↘</button>
      </div>
      <div class="row">
        <label>Speed <select class="jog-speed">${speeds.map(s => `<option value="${s}" ${s === 0.2 ? 'selected' : ''}>${s.toFixed(2)} m/s</option>`).join('')}</select></label>
      </div>
      <div class="jog-status state">not held</div>
      <p class="muted">Hold a button or the arrow keys (W/A/S/D). Works only with the physical selector in MANUAL and the supervisor allowing manual control. Release = stop.</p>
    </div>`;
  const status = root.querySelector('.jog-status');
  const speedSel = root.querySelector('.jog-speed');
  const DIRS = { f: [1, 0], b: [-1, 0], l: [0, 1], r: [0, -1], fl: [1, 1], fr: [1, -1], bl: [-1, -1], br: [-1, 1] };
  let held = null;     // {dir, session, ticket, seq, timer}
  let pending = null;  // {dir} while /press is in flight; a release clears it (review R01)
  let releasing = false;

  function body(dir) {
    const v = parseFloat(speedSel.value);
    const [a, b] = DIRS[dir];
    return { v: a * v, w: b * Math.min(0.30, v * 1.5) };
  }
  // The physical input is recorded BEFORE the press request goes out, so a release that
  // happens while it is in flight has something to cancel. A press whose input was
  // released meanwhile gives its session straight back and never refreshes it.
  async function press(dir) {
    if (held || pending || releasing) return;
    const token = { dir };
    pending = token;
    let st, data;
    try {
      ({ status: st, data } = await api('/api/manual/press', { owner }));
    } catch (e) {
      if (pending === token) pending = null;
      status.textContent = 'press failed (no connection)';
      return;
    }
    if (pending !== token) {
      if (st === 200) api('/api/manual/release', { session: data.session }).catch(() => {});
      return;
    }
    pending = null;
    if (st !== 200) { status.textContent = data.message || 'refused'; return; }
    held = { dir, session: data.session, ticket: data.ticket, seq: 0, timer: null };
    status.textContent = `holding ${dir}`;
    refresh();
  }
  async function refresh() {
    if (!held) return;
    const h = held;
    const b = body(h.dir);
    h.seq += 1;
    let st, data;
    try {
      ({ status: st, data } = await api('/api/manual/refresh', { session: h.session, ticket: h.ticket, seq: h.seq, v: b.v, w: b.w }));
    } catch (e) {
      if (held === h) { held = null; status.textContent = 'stopped: no connection'; }
      return;  // the robot drops the command 0.2 s after the last refresh by itself
    }
    if (held !== h) return;
    if (st !== 200) { status.textContent = `stopped: ${data.message}`; held = null; return; }
    h.ticket = data.ticket;
    status.textContent = `holding ${h.dir}: v ${data.v.toFixed(2)} m/s, w ${data.w.toFixed(2)} rad/s`;
    h.timer = setTimeout(refresh, 100);
  }
  async function release(why) {
    if (pending) { pending = null; status.textContent = `released (${why})`; }
    if (!held) return;
    const h = held; held = null; releasing = true;
    if (h.timer) clearTimeout(h.timer);
    try { await api('/api/manual/release', { session: h.session }); } catch (e) { /* robot expires it */ } finally { releasing = false; }
    status.textContent = `released (${why})`;
  }
  root.querySelectorAll('.jog-grid button').forEach(btn => {
    const dir = btn.dataset.dir;
    if (dir === 'stop') { btn.onclick = () => { release('stop'); api('/api/stop').catch(() => {}); }; return; }
    btn.addEventListener('pointerdown', e => { e.preventDefault(); btn.setPointerCapture(e.pointerId); press(dir); });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(ev => btn.addEventListener(ev, () => release(ev)));
  });
  const KEYS = { ArrowUp: 'f', ArrowDown: 'b', ArrowLeft: 'l', ArrowRight: 'r', w: 'f', s: 'b', a: 'l', d: 'r', W: 'f', S: 'b', A: 'l', D: 'r' };
  document.addEventListener('keydown', e => {
    const tag = (document.activeElement && document.activeElement.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;  // typing, not driving
    if (e.repeat) return;                                                   // a held key is one press
    if (e.key === ' ' || e.key === 'Escape') { e.preventDefault(); release('key'); api('/api/stop').catch(() => {}); return; }
    const dir = KEYS[e.key]; if (!dir) return;
    e.preventDefault(); press(dir);
  });
  document.addEventListener('keyup', e => { if (KEYS[e.key]) release('keyup'); });
  window.addEventListener('blur', () => release('blur'));
  window.addEventListener('pagehide', () => release('pagehide'));
  document.addEventListener('visibilitychange', () => { if (document.hidden) release('hidden'); });
  return { release };
}
