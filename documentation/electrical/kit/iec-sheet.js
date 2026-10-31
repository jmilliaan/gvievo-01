/* IEC-style electrical sheet engine (IEC 61082-1 presentation, IEC 81346 designations).
 * Units are millimetres on an A3 landscape sheet (viewBox 0 0 420 297).
 * Frame per ISO 5457 (20 mm binding margin left, 10 mm elsewhere), 10 columns numbered 0-9
 * (EPLAN style), ISO 7200 title block. Current flows top to bottom between potential rails.
 * Reuses the primitives of jis-sheet.js (load it first); adds vertical-flow symbols, tables
 * and the project data from data/project.js (window.PROJECT). */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const INK = '#111';

  const G = {
    W: 420, H: 297,
    fx: 20, fy: 10, fx2: 410, fy2: 287,   // frame
    cols: 10, strip: 5,                    // column grid
    areaY1: 15, areaY2: 250,               // drawing area between the column strips
    titleY: 255,                           // title block top
  };
  G.colW = (G.fx2 - G.fx) / G.cols;        // 39 mm

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  // x of a point in column c; f = fraction across the column (0.5 = centre)
  const col = (c, f = 0.5) => G.fx + G.colW * (c + f);

  /* ---------------- symbols, mixed into the JIS Sheet ---------------- */
  const SYM = {
    col,

    // Text defaults for IEC sheets: sans, 2.5 mm. { mono: true } for terminal numbers and codes.
    // { fill } greys out normal text; review markers ('?', '«…»') stay red.
    // { maxw } squeezes the text to that width (mm) once the fonts have loaded (see fit()).
    // Sizes are multiplied by this.textScale (TEXT_SCALE unless the page sets its own).
    text(x, y, s, o = {}) {
      const t = JIS.Sheet.prototype.text.call(this, x, y, s, Object.assign({ size: 2.5 }, o, { sans: !o.mono }));
      if (t && o.fill && t.getAttribute('fill') === INK) t.setAttribute('fill', o.fill);
      if (t && o.maxw) t.dataset.maxw = o.maxw;
      return t;
    },

    // Make (NO) or break (NC) contact on a vertical conductor, IEC 60617 S00227 / S00229.
    // The conductor must already be drawn; the contact cuts its own gap.
    // nums = [top, bottom] terminal numbers. Returns the blade mid-point for the operator link.
    contactV(x, y, kind, nums) {
      const h = 2.8;
      this.knock(x - 0.6, y - h + 0.15, x + 0.6, y + h - 0.15);
      let mid;
      if (kind === 'no') {
        this.line(x, y + h, x - 2.4, y - h + 0.5, 0.3);
        mid = { x: x - 1.2, y };
      } else {
        this.line(x, y - h, x + 2.0, y - h, 0.3);
        this.line(x, y + h, x + 2.7, y - h - 0.7, 0.3);
        mid = { x: x + 1.3, y: y - 0.3 };
      }
      if (nums) {
        const tx = kind === 'no' ? x + 1.4 : x - 1.4, a = kind === 'no' ? 'start' : 'end';
        this.text(tx, y - h + 0.9, nums[0], { size: 2, mono: true, anchor: a });
        this.text(tx, y + h + 0.1, nums[1], { size: 2, mono: true, anchor: a });
      }
      return mid;
    },

    // Manual operator for one or more contact poles (mids from contactV), drawn to the left.
    // kind: 'push' (momentary push-button), 'estop' (mushroom, latching, positive opening),
    // 'turn' (maintained selector, latching). Returns the actuator x.
    operator(mids, kind) {
      const y = mids[0].y, xa = Math.min(...mids.map(m => m.x)) - 9;
      const xr = Math.max(...mids.map(m => m.x));
      this.line(xa, y, xr, y, 0.22, '0.9 0.6');
      if (kind === 'push') {
        this.path(`M${xa + 0.9} ${y - 1.8} H${xa} V${y + 1.8} H${xa + 0.9}`, 0.3);
      } else if (kind === 'turn') {
        this.path(`M${xa - 0.9} ${y - 1.6} L${xa} ${y - 1.6} L${xa} ${y + 1.6} L${xa + 0.9} ${y + 1.6}`, 0.3);
      } else if (kind === 'estop') {
        this.path(`M${xa} ${y - 2.4} A2.4 2.4 0 0 0 ${xa} ${y + 2.4} Z`, 0.3, '#fff');
        // positive-opening mark (IEC 60947-5-1 Annex K): circle with an arrow along the link
        const cx = xa + 6;
        this.knock(cx - 1.2, y - 1.2, cx + 1.2, y + 1.2);
        el('circle', { cx, cy: y, r: 1.15, fill: '#fff', stroke: INK, 'stroke-width': 0.22 }, this.svg);
        this.path(`M${cx - 0.7} ${y} H${cx + 0.25} M${cx + 0.75} ${y} L${cx + 0.05} ${y - 0.45} L${cx + 0.05} ${y + 0.45} Z`, 0.18, INK);
      }
      if (kind === 'estop' || kind === 'turn') {
        // latching (stay-put) mark on the link
        const dx = xa + 2.6;
        this.path(`M${dx - 0.7} ${y} L${dx} ${y + 1} L${dx + 0.7} ${y}`, 0.22);
      }
      return xa;
    },

    // Terminal of a strip on a vertical conductor: circle, strip tag left, terminal number right
    terminal(x, y, strip, num) {
      this.knock(x - 0.95, y - 0.95, x + 0.95, y + 0.95);
      el('circle', { cx: x, cy: y, r: 0.95, fill: '#fff', stroke: INK, 'stroke-width': 0.25 }, this.svg);
      this.text(x - 1.8, y + 0.85, strip, { size: 2.2, anchor: 'end' });
      this.text(x + 1.8, y + 0.85, String(num), { size: 2.2, mono: true });
    },

    // A group of terminals of one strip at the same height: strip tag once, left of the first.
    // list = [[x, number], ...]
    terminals(list, y, strip) {
      const xs = list.slice().sort((a, b) => a[0] - b[0]);
      xs.forEach(([x, n]) => {
        this.knock(x - 0.95, y - 0.95, x + 0.95, y + 0.95);
        el('circle', { cx: x, cy: y, r: 0.95, fill: '#fff', stroke: INK, 'stroke-width': 0.25 }, this.svg);
        this.text(x + 1.6, y + 0.85, String(n), { size: 2.2, mono: true });
      });
      this.text(xs[0][0] - 1.8, y + 0.85, strip, { size: 2.2, anchor: 'end' });
    },

    // Interruption point at the lower end of a vertical conductor: arrow, target and reference
    offDown(x, y, target, ref) {
      this.path(`M${x - 0.9} ${y - 1.8} L${x + 0.9} ${y - 1.8} L${x} ${y} Z`, 0.1, INK);
      const k = this.textScale;
      this.text(x, y + 3.4 * k, target, { size: 2.3, anchor: 'middle' });
      if (ref) this.text(x, y + 6.6 * k, ref, { size: 2.3, anchor: 'middle', mono: true });
    },

    // Horizontal potential rail: name and source left, continuation arrow and target right.
    // toRef === false: the rail ends here (no arrow).
    rail(y, x1, x2, name, fromRef, toRef) {
      this.line(x1, y, x2, y, 0.35);
      this.text(x1 + 1, y - 1.2, name, { size: 2.5, weight: 600 });
      if (fromRef) this.text(x1 + 1 + name.length * 1.55 * this.textScale + 1.8, y - 1.2, fromRef, { size: 2.2, mono: true });
      if (toRef === false) return;
      this.path(`M${x2} ${y - 0.9} L${x2 + 1.8} ${y} L${x2} ${y + 0.9} Z`, 0.1, INK);
      if (toRef) this.text(x2 - 1, y - 1.2, toRef, { size: 2.2, mono: true, anchor: 'end' });
    },

    // Module or device: box with terminals on its top edge (default) or bottom edge.
    // terms = [{ x, name, sub? }]; the conductors end on the edge at those x.
    // label = lines written inside: first line (the tag) bold.
    module(x1, x2, y, h, terms, label, o = {}) {
      this.rect(x1, y, x2 - x1, h, 0.35);
      const bottom = o.edge === 'bottom', ey = bottom ? y + h : y, k = this.textScale;
      terms.forEach(t => {
        this.dot(t.x, ey, 0.5);
        const ty = bottom ? ey - 2.2 : ey + 4 * k;
        this.text(t.x, ty, t.name, { size: 2.4, mono: true, anchor: 'middle', weight: 600 });
        if (t.sub) this.text(t.x, bottom ? ty - 3.3 * k : ty + 3.3 * k, t.sub, { size: 2, anchor: 'middle' });
      });
      const ly = bottom ? y + 5 * k : y + (terms.some(t => t.sub) ? 13.5 : 10) * k;
      (label || []).forEach((t, i) => this.text(x1 + 3, ly + 4.2 * k * i, t,
        { size: i === 0 ? 3 : 2.4, weight: i === 0 ? 600 : 500 }));
    },

    // Circuit breaker on vertical conductors (IEC 60617 S00287: make contact with a cross
    // at the fixed contact). One pole per x, poles linked; tag and rating to the right.
    breaker(xs, y, tag, rating) {
      const h = 3.2;
      xs.forEach(x => {
        this.knock(x - 0.6, y - h + 0.15, x + 0.6, y + h - 0.15);
        this.line(x, y + h, x - 2.6, y - h + 0.6, 0.32);
        this.line(x - 0.9, y - h - 0.9, x + 0.9, y - h + 0.9, 0.28);
        this.line(x - 0.9, y - h + 0.9, x + 0.9, y - h - 0.9, 0.28);
      });
      if (xs.length > 1) this.line(xs[0] - 1.3, y, xs[xs.length - 1] - 1.3, y, 0.22, '0.9 0.6');
      const xr = xs[xs.length - 1] + 2.5;
      this.text(xr, y - 0.6, tag, { size: 3, weight: 600 });
      if (rating) this.text(xr, y + 3 * this.textScale, rating, { size: 2.3 });
    },

    // Plain box with centred lines (overview blocks, third-party devices). First line bold.
    box(x, y, w, h, lines, o = {}) {
      this.rect(x, y, w, h, o.sw || 0.35);
      const k = this.textScale, top = y + h / 2 - 2.1 * k * (lines.length - 1) + 0.9 * k;
      lines.forEach((t, i) => this.text(x + w / 2, top + 4.2 * k * i, t,
        { size: i === 0 ? (o.size1 || 2.8) : (o.size || 2.3), weight: i === 0 ? 600 : 500, anchor: 'middle' }));
    },

    // DC/DC converter or drive symbol inside a box: diagonal, input mark top-left, output mark bottom-right
    convMark(x, y, w, h, inM = '=', outM = '=') {
      this.line(x, y + h, x + w, y, 0.2);
      this.text(x + 2, y + 4.5, inM, { size: 3.2, mono: true });
      this.text(x + w - 2, y + h - 1.5, outM, { size: 3.2, mono: true, anchor: 'end' });
    },

    // Battery cells (IEC 60617 S00898) centred at x, y, horizontal plates, + on top
    cells(x, y) {
      [[-3, 3.2, 0.25], [-1.6, 1.6, 0.6], [1.6, 3.2, 0.25], [3, 1.6, 0.6]].forEach(([dy, w, sw]) =>
        this.line(x - w, y + dy, x + w, y + dy, sw));
      this.text(x + 4.5, y - 2, '+', { size: 2.6 });
    },

    // Motor: circle with M and 3~ (vertical conductors arrive at the top)
    motor(x, y, r = 7) {
      el('circle', { cx: x, cy: y, r, fill: '#fff', stroke: INK, 'stroke-width': 0.35 }, this.svg);
      this.text(x, y - 0.3, 'M', { size: 4, weight: 600, anchor: 'middle' });
      this.text(x, y + 4, '3~', { size: 2.4, anchor: 'middle' });
    },

    // Protective earth (IEC 60417-5019): earth symbol in a circle, at the lower end of a conductor
    pe(x, y) {
      el('circle', { cx: x, cy: y + 2.2, r: 3, fill: '#fff', stroke: INK, 'stroke-width': 0.25 }, this.svg);
      this.line(x, y - 0.8, x, y + 1.2, 0.3);
      this.line(x - 1.8, y + 1.2, x + 1.8, y + 1.2, 0.3);
      this.line(x - 1.2, y + 2.3, x + 1.2, y + 2.3, 0.3);
      this.line(x - 0.6, y + 3.4, x + 0.6, y + 3.4, 0.3);
    },

    // Cable: line across the conductors it groups, tag and type to the right
    cable(xs, y, tag, spec) {
      const x1 = Math.min(...xs) - 3, x2 = Math.max(...xs) + 3;
      this.line(x1, y + 1.2, x1 + 1.2, y, 0.22);
      this.line(x1 + 1.2, y, x2 - 1.2, y, 0.22);
      this.line(x2 - 1.2, y, x2, y - 1.2, 0.22);
      this.text(x2 + 1.2, y - 0.4, tag, { size: 2.4, weight: 600 });
      if (spec) this.text(x2 + 1.2, y + 3 * this.textScale, spec, { size: 2.1 });
    },

    // Interruption point at the upper start of a vertical conductor: source and reference above
    fromTop(x, y, source, ref) {
      this.path(`M${x - 0.9} ${y - 1.8} L${x + 0.9} ${y - 1.8} L${x} ${y} Z`, 0.1, INK);
      const k = this.textScale;
      this.text(x, y - 3.2 - (ref ? 3.2 * k : 0), source, { size: 2.3, anchor: 'middle' });
      if (ref) this.text(x, y - 3.2, ref, { size: 2.3, anchor: 'middle', mono: true });
    },

    // Line with an arrowhead at its end (overview diagrams)
    arrow(x1, y1, x2, y2, w = 0.35) {
      this.line(x1, y1, x2, y2, w);
      const a = Math.atan2(y2 - y1, x2 - x1), L = 2.2, B = 0.9;
      const bx = x2 - L * Math.cos(a), by = y2 - L * Math.sin(a);
      this.path(`M${x2} ${y2} L${bx - B * Math.sin(a)} ${by + B * Math.cos(a)} L${bx + B * Math.sin(a)} ${by - B * Math.cos(a)} Z`, 0.1, INK);
    },

    // Wire label (potential or signal name) written along a vertical conductor
    // (rotated -90°, so the letters stand left of the baseline: keep the baseline clear of the wire)
    wl(x, y, t) { this.text(x + 0.8 + 1.6 * this.textScale, y, t, { size: 2.1, mono: true, rotate: -90 }); },

    // Location box (dash-dot) around devices that sit in one location, label top-left
    locationBox(x, y, w, h, code, name) {
      el('rect', { x, y, width: w, height: h, fill: 'none', stroke: INK, 'stroke-width': 0.25,
        'stroke-dasharray': '4 1 0.8 1' }, this.svg);
      this.text(x + 1.5, y + 3.6, code, { size: 2.8, weight: 600 });
      if (name) this.text(x + 1.5 + code.length * 2.1 * this.textScale + 2, y + 3.6, name, { size: 2.3 });
    },

    // Device label: tag (bold) then description lines
    label(x, y, tag, lines = [], anchor = 'start') {
      this.text(x, y, tag, { size: 3, weight: 600, anchor });
      const k = this.textScale;
      lines.forEach((t, i) => this.text(x, y + (3.9 + 3.3 * i) * k, t, { size: 2.3, anchor }));
    },

    // Simple table. cols = [{ w, title, mono?, align? }], rows = arrays of cell text.
    // Returns the y below the last row.
    table(x, y, cols, rows, o = {}) {
      const rh = o.rowH || 6.2, hh = o.headH || 7, size = o.size || 2.5;
      const W = cols.reduce((a, c) => a + c.w, 0);
      const H = hh + rh * rows.length;
      el('rect', { x, y, width: W, height: H, fill: 'none', stroke: INK, 'stroke-width': 0.3 }, this.svg);
      this.line(x, y + hh, x + W, y + hh, 0.3);
      let cx = x;
      cols.forEach((c, i) => {
        if (i) this.line(cx, y, cx, y + H, 0.15);
        this.text(cx + 1.5, y + hh - 2.2, c.title, { size, weight: 600, maxw: c.w - 2.5 });
        cx += c.w;
      });
      rows.forEach((r, ri) => {
        const ry = y + hh + rh * ri;
        if (ri) this.line(x, ry, x + W, ry, 0.12);
        let rx = x;
        r.forEach((v, ci) => {
          const c = cols[ci];
          if (v !== '' && v != null) {
            const right = c.align === 'right';
            this.text(right ? rx + c.w - 1.5 : rx + 1.5, ry + rh - 1.9, v,
              { size, mono: !!c.mono, anchor: right ? 'end' : 'start', fill: o.grey && o.grey(r), maxw: c.w - 2.5 });
          }
          rx += c.w;
        });
      });
      return y + H;
    },

    // Free note block, one string per line
    note(x, y, lines, o = {}) {
      lines.forEach((t, i) => this.text(x, y + (o.lh || 3.6) * this.textScale * i, t, { size: o.size || 2.3, weight: i === 0 && o.head ? 600 : 500 }));
    },
  };

  /* ---------------- frame, column grid, title block ---------------- */
  function frame(s, m, page) {
    const P = window.PROJECT || {};
    const doc = P.doc || {};
    el('rect', { x: G.fx, y: G.fy, width: G.fx2 - G.fx, height: G.fy2 - G.fy, fill: 'none', stroke: INK, 'stroke-width': 0.6 }, s.svg);

    // column strips top and bottom
    const strip = (y) => {
      s.line(G.fx, y, G.fx2, y, 0.25);
      for (let c = 0; c < G.cols; c++) {
        if (c) s.line(G.fx + G.colW * c, y - G.strip, G.fx + G.colW * c, y, 0.25);
        s.text(col(c), y - 1.4, String(c), { size: 2.8, anchor: 'middle', mono: true });
      }
    };
    if (!m.noGrid) {
      strip(G.areaY1);
      s.line(G.fx, G.areaY2, G.fx2, G.areaY2, 0.25);
      strip(G.titleY);
    }

    // title block: six blocks across, four rows
    const y0 = G.titleY, y1 = G.fy2, rh = (y1 - y0) / 4;
    const bx = [G.fx, 112, 166, 202, 318, 358, G.fx2];
    s.line(G.fx, y0, G.fx2, y0, 0.45);
    bx.slice(1, -1).forEach(x => s.line(x, y0, x, y1, 0.3));
    const cap = (x, y, t) => s.text(x + 1.2, y + 2.6, t, { size: 1.8, fill: '#555' });
    const val = (x, y, t, o = {}) => s.text(x + 1.2, y + rh - 1.6, t, Object.assign({ size: 2.6 }, o));
    const w = i => bx[i + 1] - bx[i] - 3;

    // block 1: revision table
    const rev = doc.revisions || [];
    const RC = [0, 7, 52, 74];             // column offsets: rev, change, date, name
    ['Rev', 'Change', 'Date', 'Name'].forEach((t, i) => s.text(bx[0] + 1.2 + RC[i], y0 + 5, t, { size: 1.9, weight: 600 }));
    RC.slice(1).forEach(dx => s.line(bx[0] + dx, y0, bx[0] + dx, y1, 0.12));
    for (let i = 1; i < 4; i++) s.line(bx[0], y0 + rh * i, bx[1], y0 + rh * i, 0.12);
    rev.slice(-3).forEach((r, i) => {
      const yy = y0 + rh * (i + 2) - 2.2;
      s.text(bx[0] + 1.2, yy, r.rev, { size: 2.2 });
      s.text(bx[0] + 1.2 + RC[1], yy, r.change, { size: 2.2, maxw: RC[2] - RC[1] - 2.4 });
      s.text(bx[0] + 1.2 + RC[2], yy, r.date, { size: 2.0, mono: true });
      s.text(bx[0] + 1.2 + RC[3], yy, r.name, { size: 2.2 });
    });

    // block 2: legal owner
    cap(bx[1], y0, 'Legal owner');
    s.text(bx[1] + 3, y0 + 13, doc.owner, { size: 4, weight: 600, maxw: w(1) - 3 });
    (doc.ownerLines || []).forEach((t, i) => s.text(bx[1] + 3, y0 + 19 + 3.4 * s.textScale * i, t, { size: 2.3, maxw: w(1) - 3 }));

    // block 3: date / created / checked / approved
    [['Date of issue', doc.date], ['Created by', doc.created], ['Checked by', doc.checked], ['Approved by', doc.approved]]
      .forEach(([c, v], i) => {
        if (i) s.line(bx[2], y0 + rh * i, bx[3], y0 + rh * i, 0.12);
        cap(bx[2], y0 + rh * i, c); val(bx[2], y0 + rh * i, v, { size: 2.4, maxw: w(2) });
      });

    // block 4: title, document type, page description
    cap(bx[3], y0, 'Title');
    s.text(bx[3] + 2, y0 + 8.4, doc.title, { size: 3.4, weight: 600, maxw: w(3) });
    s.line(bx[3], y0 + rh * 1.5, bx[4], y0 + rh * 1.5, 0.12);
    cap(bx[3], y0 + rh * 1.5, 'Document type');
    s.text(bx[3] + 2, y0 + rh * 1.5 + 6.6, doc.type, { size: 2.6 });
    s.line(bx[3], y0 + rh * 2.5, bx[4], y0 + rh * 2.5, 0.25);
    cap(bx[3], y0 + rh * 2.5, 'Page description');
    s.text(bx[3] + 2, y0 + rh * 4 - 2.4, m.description, { size: 3.6, weight: 600, maxw: w(3) });

    // block 5: function / location / document kind / language
    [['Function (=)', m.func || ''], ['Location (+)', m.location || ''], ['Document kind', m.kind || '&EFS'], ['Language', doc.language || 'en']]
      .forEach(([c, v], i) => {
        if (i) s.line(bx[4], y0 + rh * i, bx[5], y0 + rh * i, 0.12);
        cap(bx[4], y0 + rh * i, c); val(bx[4], y0 + rh * i, v, { size: 2.6, mono: true, maxw: w(4) });
      });

    // block 6: document number, revision, page, number of pages
    const drawn = (P.pages || []).filter(p => p.drawn).length;
    [['Document number', doc.number], ['Revision', doc.revision], ['Page', String(page)], ['Number of pages', String(drawn || '')]]
      .forEach(([c, v], i) => {
        if (i) s.line(bx[5], y0 + rh * i, bx[6], y0 + rh * i, 0.12);
        cap(bx[5], y0 + rh * i, c);
        val(bx[5], y0 + rh * i, v, { size: i === 2 ? 3.6 : 2.6, weight: i === 2 ? 600 : 500, mono: i > 0 });
      });

    // draft stamp in the margin
    if (doc.status) s.text(14, G.fy2 - 2, doc.status, { size: 2.6, weight: 600, rotate: -90, fill: '#555' });
  }

  // All text is drawn this much larger than the sizes written in the code (owner, 2026-11-01:
  // 10-20 % bigger). A page that has no room can pass a smaller textScale to IEC.page().
  const TEXT_SCALE = 1.2;

  // Squeeze texts marked { maxw } that came out wider than their box (table cells, title block).
  function fit(svg) {
    svg.querySelectorAll('text[data-maxw]').forEach(t => {
      const max = +t.dataset.maxw;
      if (t.getComputedTextLength() > max) {
        t.setAttribute('textLength', max);
        t.setAttribute('lengthAdjust', 'spacingAndGlyphs');
      }
    });
  }

  // Layout check (open a page with #check): lists texts that overlap other texts, cross a
  // line or a box edge, or leave the frame. Written into <pre id="check"> for headless runs.
  function report(svg) {
    const inv = svg.getScreenCTM().inverse();
    const mm = r => {
      const p = new DOMPoint(r.left, r.top).matrixTransform(inv), q = new DOMPoint(r.right, r.bottom).matrixTransform(inv);
      return { x1: p.x, y1: p.y, x2: q.x, y2: q.y };
    };
    const texts = [...svg.querySelectorAll('text')].map(t => {
      const b = mm(t.getBoundingClientRect()), rot = t.hasAttribute('transform');
      const sh = rot ? { x: 0.2 * (b.x2 - b.x1), y: 0.1 } : { x: 0.1, y: 0.2 * (b.y2 - b.y1) };
      return { s: t.textContent, b: { x1: b.x1 + sh.x, x2: b.x2 - sh.x, y1: b.y1 + sh.y, y2: b.y2 - sh.y } };
    });
    const segs = [];
    svg.querySelectorAll('line').forEach(l => segs.push(['x1', 'y1', 'x2', 'y2'].map(a => +l.getAttribute(a))));
    svg.querySelectorAll('rect[stroke]').forEach(r => {
      const x = +r.getAttribute('x'), y = +r.getAttribute('y'), w = +r.getAttribute('width'), h = +r.getAttribute('height');
      segs.push([x, y, x + w, y], [x, y + h, x + w, y + h], [x, y, x, y + h], [x + w, y, x + w, y + h]);
    });
    const hit = (b, [x1, y1, x2, y2]) => {
      if (x1 === x2) return x1 > b.x1 && x1 < b.x2 && Math.max(y1, y2) > b.y1 && Math.min(y1, y2) < b.y2;
      if (y1 === y2) return y1 > b.y1 && y1 < b.y2 && Math.max(x1, x2) > b.x1 && Math.min(x1, x2) < b.x2;
      for (let i = 0; i <= 20; i++) {
        const x = x1 + (x2 - x1) * i / 20, y = y1 + (y2 - y1) * i / 20;
        if (x > b.x1 && x < b.x2 && y > b.y1 && y < b.y2) return true;
      }
      return false;
    };
    const status = ((window.PROJECT || {}).doc || {}).status;
    const out = [];
    texts.forEach((a, i) => {
      const b = a.b, at = `"${a.s}" @${b.x1.toFixed(0)},${b.y2.toFixed(0)}`;
      if ((b.x1 < G.fx || b.x2 > G.fx2 || b.y1 < G.fy || b.y2 > G.fy2) && a.s !== status) out.push(`frame  ${at}`);
      texts.slice(i + 1).forEach(c => {
        const o = c.b;
        if (b.x1 < o.x2 && o.x1 < b.x2 && b.y1 < o.y2 && o.y1 < b.y2) out.push(`text   ${at}  x  "${c.s}"`);
      });
      if (segs.some(sg => hit(b, sg))) out.push(`line   ${at}`);
    });
    const pre = document.createElement('pre');
    pre.id = 'check';
    pre.textContent = out.join('\n') || 'OK';
    document.body.appendChild(pre);
  }

  /* ---------------- render + export ---------------- */
  function render(host, spec) {
    if (location.hash === '#bare') document.body.classList.add('bare');
    const svg = el('svg', { viewBox: `0 0 ${G.W} ${G.H}`, xmlns: NS, role: 'img', 'aria-label': spec.description }, host);
    el('rect', { x: 0, y: 0, width: G.W, height: G.H, fill: '#fff' }, svg);
    const s = new JIS.Sheet(svg);
    Object.assign(s, SYM);
    s.textScale = TEXT_SCALE;
    frame(s, spec, spec.page);
    s.textScale = spec.textScale || TEXT_SCALE;
    spec.draw(s, { G, col });
    const ready = (document.fonts ? document.fonts.ready : Promise.resolve()).then(() => fit(svg));
    if (location.hash === '#check') ready.then(() => report(svg));

    const status = document.getElementById('status');
    if (s.flags.length) {
      if (status) status.textContent = `${s.flags.length} item(s) in red need review`;
      console.warn('Review before issue:\n' + s.flags.join('\n'));
    }
    window.IEC.flags = s.flags;
    const png = document.getElementById('png');
    const pdf = document.getElementById('pdf');
    if (pdf) pdf.addEventListener('click', () => window.print());
    if (png) png.addEventListener('click', async () => {
      if (!window.htmlToImage) { status.textContent = 'Export library did not load — check internet connection'; return; }
      png.disabled = true;
      status.textContent = 'Rendering…';
      try {
        await document.fonts.ready;
        const url = await htmlToImage.toPng(host, {
          width: 1587, height: 1123, pixelRatio: 3.125, backgroundColor: '#ffffff',
          style: { width: '1587px', height: '1123px', margin: '0', boxShadow: 'none' },
        });
        const a = document.createElement('a');
        a.href = url;
        a.download = `${spec.file}.png`;
        document.body.appendChild(a); a.click(); a.remove();
        status.textContent = 'Saved 4960 × 3508 PNG (A3, 300 dpi)';
      } catch (e) {
        console.error(e);
        status.textContent = 'Export failed — see console';
      } finally {
        png.disabled = false;
      }
    });
  }

  // Page from the project page list: fills the toolbar (title, prev / next, export buttons)
  // and the title-block fields, then renders. File names are iec-page-NN.html.
  function page(no, draw, o = {}) {
    const pages = (window.PROJECT && PROJECT.pages) || [];
    const pg = pages.find(p => p.no === no) || { desc: '', kind: '&EFS' };
    const drawn = pages.filter(p => p.drawn);
    const i = drawn.findIndex(p => p.no === no);
    const href = p => `iec-page-${String(p.no).padStart(2, '0')}.html`;
    const bar = document.getElementById('toolbar');
    if (bar) {
      const prev = drawn[i - 1], next = drawn[i + 1];
      bar.innerHTML =
        `<strong>Page ${no} · ${pg.desc}</strong>` +
        (prev ? `<a href="${href(prev)}">◀ ${prev.no}</a>` : '') +
        `<a href="iec-page-02.html">Contents</a>` +
        (next ? `<a href="${href(next)}">${next.no} ▶</a>` : '') +
        '<button type="button" class="primary" id="png">Download PNG</button>' +
        '<button type="button" id="pdf">Print / PDF</button>' +
        '<span class="status" id="status">A3 landscape · vector</span>';
    }
    document.title = `Page ${no} · ${pg.desc}`;
    render(document.getElementById('sheet'), Object.assign({
      page: no, file: `iec-page-${String(no).padStart(2, '0')}`,
      description: pg.desc, location: pg.loc, func: pg.func, kind: pg.kind, draw,
    }, o));
  }

  window.IEC = { render, page, G, col };
})();
