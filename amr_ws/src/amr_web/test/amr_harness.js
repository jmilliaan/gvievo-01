// Runs the real static/amr.js against a stub DOM with a manual timer queue, so its shared
// helpers can be checked without a browser. Driven by test_amr_js.py; prints one JSON line.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const timers = [];
const els = {};
const stubEl = () => ({ hidden: false, className: '', innerHTML: '', textContent: '', title: '', dataset: {},
  classList: (() => { const c = new Set(); return { toggle(k, on) { (on ?? !c.has(k)) ? c.add(k) : c.delete(k); },
    add(k) { c.add(k); }, remove(k) { c.delete(k); }, contains: k => c.has(k) }; })(), querySelectorAll: () => [], addEventListener() {},
  setAttribute() {}, appendChild() {} });
const document = {
  hidden: false, documentElement: stubEl(), body: stubEl(),
  getElementById: id => (id in els ? els[id] : null), querySelector: () => null, querySelectorAll: () => [],
  addEventListener() {}, createElement: stubEl,
};
let fetchImpl = () => Promise.reject(new Error('offline'));
const ctx = {
  console, JSON, Math, Promise, Date, Object, Array, String, Number, Error, encodeURIComponent,
  document, window: { addEventListener() {}, location: { reload() {} } },
  localStorage: { getItem: () => null, setItem() {} },
  navigator: {}, AbortController,
  fetch: (...a) => fetchImpl(...a),
  setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  clearTimeout() {}, setInterval: () => 0, clearInterval() {},
};
ctx.window.document = document;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'amr_web', 'static', 'amr.js'), 'utf8'), ctx);

const settle = () => new Promise(r => setImmediate(r));
const reply = (status, data) => () => Promise.resolve({ status, ok: status === 200, statusText: 'x', json: async () => data });
const cases = {
  panelVerdict() {
    const v = p => ctx.panelVerdict(p);
    return { fresh: v({ age_s: 0.4, valid: true, mode_auto: true }), stale: v({ age_s: 0.6, valid: true, mode_auto: false }),
             invalid: v({ age_s: 0.1, valid: false }), manual: v({ age_s: 0.1, valid: true, mode_auto: false }),
             missing: v(null), fresh_s: vm.runInContext('FRESH_S', ctx) };
  },
  async act() {
    els.log = stubEl(); els.msg = stubEl();
    const out = {};
    fetchImpl = reply(200, { ok: false, message: 'not at a station' });
    await ctx.act('/api/x', {}, { msgEl: 'msg' });
    out.okFalse = { text: els.msg.textContent, bad: els.msg.classList.contains('bad'), log: els.log.textContent };
    fetchImpl = reply(200, { message: 'done' });
    await ctx.act('/api/x', {}, { msgEl: 'msg', prefix: 'teach x: ' });
    out.ok200 = { text: els.msg.textContent, bad: els.msg.classList.contains('bad'), log: els.log.textContent.split('\n')[0] };
    fetchImpl = reply(409, { message: 'refused: moving' });
    const r = await ctx.act('/api/x');
    out.refused = { status: r.status, log: els.log.textContent.split('\n')[0] };
    fetchImpl = () => Promise.reject(new Error('offline'));
    out.none = await ctx.act('/api/x', {}, { msgEl: 'msg', noResponse: 'no response: the order may not be set' });
    out.noneText = els.msg.textContent;
    out.noneBad = els.msg.classList.contains('bad');
    return out;
  },
  alarmRow() {
    // the Home row as it was written inline before D63, byte for byte
    const esc = vm.runInContext('esc', ctx), LV = vm.runInContext('LV', ctx);
    const a = { level: 'warn', title: 'Drives <off>', action: 'Press Reset', code: 'X_1', clears_by: 'Reset', detail: 'd&d' };
    const old = `<div class="al-row standing ${LV[a.level]}"><span class="al-lv">${esc(a.level)}</span>` +
      `<span class="al-msg"><span class="al-what">${esc(a.title)}</span>${esc(a.action)}` +
      `<i class="al-detail">${esc(a.code)}${a.clears_by ? ` · clears by ${esc(a.clears_by)}` : ''} · ${esc(a.detail)}</i></span></div>`;
    const now = ctx.alarmRow(a, `${esc(a.code)}${a.clears_by ? ` · clears by ${esc(a.clears_by)}` : ''} · ${esc(a.detail)}`);
    return { same: old === now, escaped: now.includes('&lt;off&gt;') };
  },
  async every() {
    timers.length = 0;
    let runs = 0, errors = 0;
    ctx.every(700, async () => { runs += 1; throw new Error('dropped request'); }, { onError: () => { errors += 1; } });
    await settle();
    const first = timers.filter(t => t.ms === 700).length;
    timers.filter(t => t.ms === 700).forEach(t => t.fn());
    await settle();
    document.hidden = true;
    let hiddenRuns = 0;
    ctx.every(900, () => { hiddenRuns += 1; }, { visibleOnly: true });
    await settle();
    document.hidden = false;
    return { runs, errors, rescheduled: first === 1 && timers.filter(t => t.ms === 700).length === 2,
             hiddenRuns, hiddenRescheduled: timers.some(t => t.ms === 900) };
  },
};

(async () => {
  const out = {};
  try {
    await settle();
    for (const name of process.argv.slice(2)) out[name] = await cases[name]();
  } catch (e) { out.error = String(e && e.stack || e); }
  console.log(JSON.stringify(out));
  process.exit(0);
})();
