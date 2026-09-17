// Runs the real static/editor.js against a fake DOM, a fake MapView and a scripted api.
// Driven by test_editor_js.py; prints one JSON line of results.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const els = {};
function el(id, tag) {
  const e = { id, tagName: tag || 'DIV', classList: new Set(), dataset: {}, listeners: {}, textContent: '', value: '', options: undefined,
    innerHTML: '', children: [], addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    appendChild(c) { this.children.push(c); }, querySelector() { return null; } };
  e.classList.toggle = function (c, on) { if (on === undefined ? !this.has(c) : on) this.add(c); else this.delete(c); };
  els[id] = e; return e;
}
['ed-canvas', 'tool-start', 'tool-line', 'btn-start-survey', 'btn-undo', 'btn-redo', 'btn-clear', 'btn-validate', 'btn-save',
 'btn-mission', 'ed-steps', 'ed-result', 'ed-hint', 'ed-route-id', 'ed-load', 'ed-map'].forEach(id => el(id));
el('ed-repeat', 'INPUT').value = '1';
el('ed-speed', 'INPUT').value = '0.40';   // a NUMBER input, as in editor.html (not a <select>)
['fl', 'f'].forEach(() => {});
['turn-ccw-45', 'turn-cw-45'].forEach(id => { const b = el(id, 'BUTTON'); b.dataset = { dir: id.includes('ccw') ? 'ccw' : 'cw', ang: '45' }; });
const doc = { getElementById: id => els[id] || el(id), querySelectorAll: () => [], createElement: tag => ({ tagName: tag.toUpperCase(), value: '', textContent: '' }), fonts: { ready: Promise.resolve() } };

class MapView { constructor() { this.overlays = []; this.meta = null; this.tool = null; } draw() {} async load(m, r) { this.meta = { map_id: m, revision: r, frame_id: 'map' }; } }
const scripted = {};
const calls = [];
async function api(url, body) { calls.push({ url, body }); return scripted[url] ? scripted[url](body) : { status: 200, data: {} }; }
const ctx = { document: doc, window: {}, MapView, INK: new Proxy({}, { get: () => '#000000' }), alpha: () => '#00000055',
  esc: v => String(v ?? ''), num: (v, dp) => Number(v).toFixed(dp), log: () => {}, api, apiGet: u => api(u), lastState: null,
  fillMapSelect: async sel => { sel.options = { length: 1 }; sel.selectedIndex = 0; sel.value = 'm1/1'; return []; },
  console, setTimeout, crypto: { randomUUID: () => 'x' } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'amr_web', 'static', 'editor.js'), 'utf8'), ctx);
const flush = () => new Promise(r => setImmediate(r));

(async () => {
  const out = {};
  scripted['/api/footprint'] = () => ({ status: 200, data: { polygon: [[-0.5, -0.35], [1.1, -0.35], [1.1, 0.35], [-0.5, 0.35]], margin_m: 0.1, reach_m: 1.15 } });
  scripted['/api/maps/m1/1'] = () => ({ status: 200, data: { routes: { slow: [1] } } });
  for (let i = 0; i < 5; i++) await flush();
  out.new_draft_speed = els['ed-speed'].value;                       // refresh() ran on the new draft: 0.40, no TypeError
  // load a saved route with 0.3: shown as 0.3, model untouched
  scripted['/api/maps/m1/1/routes/slow/1'] = () => ({ status: 200, data: { ok: true, route: { route_id: 'slow', start: { x_m: 0, y_m: 0, yaw_deg: 0 }, steps: [], repeat_count: 1, limits: { linear_mps: 0.3 } }, issues: [] } });
  els['ed-load'].value = 'slow/1';
  await els['ed-load'].onchange({ target: els['ed-load'] });
  for (let i = 0; i < 3; i++) await flush();
  out.loaded_speed_shown = els['ed-speed'].value;
  // a save carries the loaded value, not the default
  scripted['/api/maps/m1/1/routes/save'] = body => { out.saved_limits = body.limits; return { status: 200, data: { route_id: 'slow', revision: 2, sha256: 'abcdef123456' } }; };
  await els['btn-save'].onclick();
  for (let i = 0; i < 3; i++) await flush();
  // reset to a new draft (map change) goes back to 0.40
  els['ed-map'].value = 'm1/1';
  await els['ed-map'].onchange({ target: els['ed-map'] });
  for (let i = 0; i < 3; i++) await flush();
  out.reset_speed = els['ed-speed'].value;
  console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
