// MapView: a map bundle image on a canvas with pan/zoom and the three coordinate
// systems the editor needs. Formulas mirror amr_maps.grid.world_to_pixel /
// pixel_to_world exactly (origin, resolution, origin yaw, row inversion).
//   world (x, y) metres  <->  pixel (u, v) image coords, v down  <->  screen (sx, sy)
class MapView {
  constructor(canvas) {
    this.canvas = canvas; this.ctx = canvas.getContext('2d');
    this.meta = null; this.img = null; this.scale = 1; this.ox = 0; this.oy = 0;
    this.overlays = []; this._drag = null; this.onClick = null; this.onDrag = null;
    canvas.addEventListener('wheel', e => { e.preventDefault(); this.zoomAt(e.offsetX, e.offsetY, e.deltaY < 0 ? 1.15 : 1/1.15); });
    canvas.addEventListener('mousedown', e => { this._drag = { x: e.offsetX, y: e.offsetY, moved: false, btn: e.button, t0: Date.now() }; });
    canvas.addEventListener('mousemove', e => {
      if (!this._drag) return;
      const dx = e.offsetX - this._drag.x, dy = e.offsetY - this._drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) this._drag.moved = true;
      if (this.onDrag && this._drag.btn === 0 && this.tool) { this.onDrag(this.screenToWorld(this._drag.x, this._drag.y), this.screenToWorld(e.offsetX, e.offsetY), false); this.draw(); return; }
      this.ox += dx; this.oy += dy; this._drag.x = e.offsetX; this._drag.y = e.offsetY; this.draw();
    });
    const up = e => {
      if (!this._drag) return;
      const d = this._drag; this._drag = null;
      const w = this.screenToWorld(e.offsetX, e.offsetY);
      if (this.tool && d.btn === 0) {
        if (this.onDrag && d.moved) this.onDrag(this.screenToWorld(d.x, d.y), w, true);
        else if (this.onClick) this.onClick(w);
      }
      this.draw();
    };
    canvas.addEventListener('mouseup', up);
    canvas.addEventListener('mouseleave', () => { this._drag = null; });
    canvas.addEventListener('contextmenu', e => e.preventDefault());
    this._resize(); window.addEventListener('resize', () => { this._resize(); this.draw(); });
  }
  _resize() { const r = this.canvas.getBoundingClientRect(); this.canvas.width = Math.max(200, r.width); this.canvas.height = Math.max(200, r.height); }
  // Returns false when a later load() superseded this one while it was in flight: the
  // picture and its metadata always belong to the same, most recently requested map (R12).
  async load(mapId, rev) {
    const token = this._loadToken = {};
    const { data } = await apiGet(`/api/maps/${mapId}/${rev}`);
    if (this._loadToken !== token) return false;
    const im = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = `/api/maps/${mapId}/${rev}/image.png?s=${data.sha256.slice(0, 8)}`; });
    if (this._loadToken !== token) return false;
    this.meta = data; this.img = im;
    this.fit(); this.draw();
    return true;
  }
  // Live grid (unified plan §6.4): metadata and image share one snapshot id; the
  // grid may grow and move its origin between snapshots, so meta and image are
  // swapped together. The view is fitted only the first time (or when asked),
  // never on every update.
  async loadLive(meta) {
    if (!meta || !meta.available) return false;
    if (this._liveSnapshot === meta.snapshot && this.meta && this.meta.generation === meta.generation) return false;
    const im = await new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = `/api/live/map.png?snapshot=${meta.snapshot}`; });
    if (!im) return false;  // a newer snapshot appeared; the next poll gets it
    const first = !this.img || !this.meta || this.meta.generation !== meta.generation;
    this.meta = meta; this.img = im; this._liveSnapshot = meta.snapshot;
    if (first) this.fit();
    this.draw();
    return true;
  }
  clearLive() { this.meta = null; this.img = null; this._liveSnapshot = null; this.draw(); }
  fit() {
    if (!this.img) return;
    this.scale = Math.min(this.canvas.width / this.img.width, this.canvas.height / this.img.height) * 0.95;
    this.ox = (this.canvas.width - this.img.width * this.scale) / 2; this.oy = (this.canvas.height - this.img.height * this.scale) / 2;
  }
  zoomAt(sx, sy, f) { this.ox = sx - (sx - this.ox) * f; this.oy = sy - (sy - this.oy) * f; this.scale *= f; this.draw(); }
  // --- coordinates (see amr_maps.grid) ---
  worldToPixel(x, y) {
    const m = this.meta, dx = x - m.origin[0], dy = y - m.origin[1], c = Math.cos(m.origin[2]), s = Math.sin(m.origin[2]);
    const gx = c * dx + s * dy, gy = -s * dx + c * dy;
    return [gx / m.resolution, m.height - gy / m.resolution];
  }
  pixelToWorld(u, v) {
    const m = this.meta, gx = u * m.resolution, gy = (m.height - v) * m.resolution, c = Math.cos(m.origin[2]), s = Math.sin(m.origin[2]);
    return [m.origin[0] + c * gx - s * gy, m.origin[1] + s * gx + c * gy];
  }
  pixelToScreen(u, v) { return [this.ox + u * this.scale, this.oy + v * this.scale]; }
  screenToPixel(sx, sy) { return [(sx - this.ox) / this.scale, (sy - this.oy) / this.scale]; }
  worldToScreen(x, y) { const [u, v] = this.worldToPixel(x, y); return this.pixelToScreen(u, v); }
  screenToWorld(sx, sy) { const [u, v] = this.screenToPixel(sx, sy); return this.pixelToWorld(u, v); }
  // --- drawing ---
  draw() {
    const c = this.ctx; c.fillStyle = '#0d0f12'; c.fillRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.img) return;
    c.imageSmoothingEnabled = false;
    c.drawImage(this.img, this.ox, this.oy, this.img.width * this.scale, this.img.height * this.scale);
    this.overlays.forEach(fn => fn(c, this));
  }
  // helpers for overlays
  line(x1, y1, x2, y2, color, width) { const c = this.ctx, a = this.worldToScreen(x1, y1), b = this.worldToScreen(x2, y2); c.strokeStyle = color; c.lineWidth = width || 2; c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke(); }
  dot(x, y, color, r) { const c = this.ctx, p = this.worldToScreen(x, y); c.fillStyle = color; c.beginPath(); c.arc(p[0], p[1], r || 4, 0, 2 * Math.PI); c.fill(); }
  text(x, y, s, color) { const c = this.ctx, p = this.worldToScreen(x, y); c.fillStyle = color || '#fff'; c.font = '12px system-ui'; c.fillText(s, p[0] + 6, p[1] - 6); }
  arrow(x, y, yaw, len, color) { this.line(x, y, x + len * Math.cos(yaw), y + len * Math.sin(yaw), color, 3); this.dot(x, y, color, 5); }
  points(pts, color) { const c = this.ctx; c.fillStyle = color; pts.forEach(p => { const q = this.worldToScreen(p[0], p[1]); c.fillRect(q[0] - 1, q[1] - 1, 2, 2); }); }
  polygon(pts, color) { const c = this.ctx; c.strokeStyle = color; c.lineWidth = 1.5; c.beginPath(); pts.forEach((p, i) => { const s = this.worldToScreen(p[0], p[1]); i ? c.lineTo(s[0], s[1]) : c.moveTo(s[0], s[1]); }); c.closePath(); c.stroke(); }
  footprint(x, y, yaw, poly, color) { const c = Math.cos(yaw), s = Math.sin(yaw); this.polygon(poly.map(p => [x + c * p[0] - s * p[1], y + s * p[0] + c * p[1]]), color); }
}
async function fillMapSelect(sel) {
  const { data } = await apiGet('/api/maps');
  sel.innerHTML = '';
  data.forEach(m => m.revisions.forEach(r => { if (r.error) return; const o = document.createElement('option'); o.value = `${m.map_id}/${r.revision}`; o.textContent = `${m.map_id} rev${r.revision} (${r.created})`; sel.appendChild(o); }));
  return data;
}
