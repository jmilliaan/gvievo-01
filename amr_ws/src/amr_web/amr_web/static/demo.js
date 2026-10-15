// The DEMO page (templates/demo.html), the landing page. Read-only: the one request it makes is
// GET /api/demo, whose every word is decided server-side in demo.py.
//   Left:  the safety scanner's live view. A static layer (range rings, the scanner's field of
//          view, its protective/warning fields from scanner_fields.yaml, the vehicle) is drawn
//          only on resize; a live layer draws the sweep and the points with a short trail.
//   Right: feature slides (content.json), sliding, with a timed progress bar.
(function () {
  'use strict';

  var POLL_MS = 500;
  var STALE_MS = 5000;      // no answer this long: the live side says "standing by"
  var PAUSE_MS = 30000;     // a visitor who taps a slide gets to read it
  var FPS_MS = 1000 / 30;   // the sweep is capped at 30 fps (the N97 runs warm)
  var TRAIL = 4;            // scans kept, oldest faintest
  var SCANNER_X = 0.964;    // demo.SCANNER_X_M: where the sweep starts, in front of base_link
  var FOV = 95 * Math.PI / 180;  // the usable half-angle (nanoscan3.yaml angle_start/end)
  var SWEEP_S = 2.2;        // one pass across the field of view
  var DOT = 2.25, DOT_LIT = 3.4;  // point radius in px, and just behind the beam (75 % of 3 / 4.5)

  var $ = function (id) { return document.getElementById(id); };
  var live = document.querySelector('.d-live');
  var statusBox = document.querySelector('.d-status');
  var css = getComputedStyle(document.body);
  var color = function (name) { return css.getPropertyValue(name).trim(); };
  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var lastOk = 0;

  // ---- the radar: vehicle at the centre, forward = up ----
  var bg = $('d-radar-bg'), fg = $('d-radar');
  var bctx = bg.getContext('2d'), ctx = fg.getContext('2d');
  function parse(s) { try { return JSON.parse(s || '[]'); } catch (e) { return []; } }
  var outline = parse(fg.dataset.outline);
  var zones = parse(fg.dataset.zones);
  var rangeM = Number(fg.dataset.view) || 3;  // shown out to this far from the scanner (demo.RADAR_M)
  var trail = [];          // [{points, near}] newest last
  var status = 'standby';
  var W = 0, H = 0, K = 1, CX = 0, CY = 0;

  // body frame x forward, y left -> screen up, left. The view is anchored on the scanner, low
  // in the panel, so the rangeM in front of it fills the radar; the vehicle runs off the bottom.
  function sx(x, y) { return CX - y * K; }
  function sy(x, y) { return CY - x * K; }

  function fit(c, g) {
    var dpr = window.devicePixelRatio || 1;
    var w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
    }
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    return [w, h];
  }

  function poly(g, pts) {
    g.beginPath();
    pts.forEach(function (p, i) { (i ? g.lineTo : g.moveTo).call(g, sx(p[0], p[1]), sy(p[0], p[1])); });
    g.closePath();
  }

  var ZONE = {
    slow: { css: '--z-slow', fill: 0.16 },
    stop: { css: '--z-stop', fill: 0.20 },
    protective: { css: '--z-protective', fill: 0.26 },
  };

  function drawStatic() {
    var wh = fit(bg, bctx); W = wh[0]; H = wh[1];
    fit(fg, ctx);
    if (!W || !H) return;
    // as large as the panel allows, then the scanner as low as it can sit with the 3 m arc
    // still touching the top - the space ahead of the vehicle gets all the height
    K = Math.min((W / 2 - 8) / rangeM, (H * 0.92 - 10) / rangeM);
    var scannerY = Math.min(H * 0.92, 10 + rangeM * K);
    CX = W / 2; CY = scannerY + SCANNER_X * K;  // CY is base_link's row; the scanner is ahead of it
    bctx.clearRect(0, 0, W, H);

    // field of view: the wedge the scanner covers
    var ox = sx(SCANNER_X, 0), oy = sy(SCANNER_X, 0), R = rangeM * K;
    bctx.beginPath();
    bctx.moveTo(ox, oy);
    bctx.arc(ox, oy, R, -Math.PI / 2 - FOV, -Math.PI / 2 + FOV);
    bctx.closePath();
    bctx.fillStyle = color('--wedge');
    bctx.fill();

    // range rings around the scanner, 1 m apart
    bctx.strokeStyle = color('--ring');
    bctx.lineWidth = 1.5;
    bctx.fillStyle = color('--ink-3');
    bctx.font = '13px "IBM Plex Sans", sans-serif';
    for (var r = 1; r <= rangeM; r++) {
      bctx.beginPath();
      bctx.arc(ox, oy, r * K, 0, Math.PI * 2);
      bctx.stroke();
      bctx.fillText(r + ' m', ox + 6, oy - r * K + 15);
    }

    // the scanner's fields, outer first
    zones.forEach(function (z) {
      var s = ZONE[z.kind] || ZONE.slow;
      poly(bctx, z.poly);
      bctx.globalAlpha = s.fill;
      bctx.fillStyle = color(s.css);
      bctx.fill();
      bctx.globalAlpha = 0.9;
      bctx.lineWidth = 2;
      bctx.strokeStyle = color(s.css);
      bctx.stroke();
      bctx.globalAlpha = 1;
    });

    // the vehicle, with a forward arrow
    if (outline.length > 2) {
      poly(bctx, outline);
      bctx.shadowColor = 'rgba(200,16,46,.35)';
      bctx.shadowBlur = 16;
      bctx.fillStyle = color('--brand');
      bctx.fill();
      bctx.shadowBlur = 0;
      var fx = Math.max.apply(null, outline.map(function (p) { return p[0]; }));
      bctx.beginPath();
      bctx.moveTo(CX, sy(fx, 0) + 8);
      bctx.lineTo(CX - 11, sy(fx, 0) + 25);
      bctx.lineTo(CX + 11, sy(fx, 0) + 25);
      bctx.closePath();
      bctx.fillStyle = '#fff';
      bctx.fill();
    }
    // the scanner itself
    bctx.beginPath();
    bctx.arc(ox, oy, 6, 0, Math.PI * 2);
    bctx.fillStyle = '#0EA5A4';
    bctx.fill();
  }

  var sweepRGB = color('--sweep') || '14,165,164';
  function drawLive(t) {
    if (!W || !H) return;
    ctx.clearRect(0, 0, W, H);
    var ox = sx(SCANNER_X, 0), oy = sy(SCANNER_X, 0);
    var active = status !== 'standby';

    // the sweep: a soft beam swinging across the field of view, with a fading tail
    var ang = 0;
    if (active && !reduced) {
      var phase = (t / 1000 / SWEEP_S) % 2;
      var f = phase < 1 ? phase : 2 - phase;         // there and back
      ang = -Math.PI / 2 - FOV + 2 * FOV * f;
      var dir = phase < 1 ? 1 : -1;
      var R = rangeM * K;
      for (var i = 0; i < 10; i++) {
        var a0 = ang - dir * i * 0.035, a1 = ang - dir * (i + 1) * 0.035;
        ctx.beginPath();
        ctx.moveTo(ox, oy);
        ctx.arc(ox, oy, R, Math.min(a0, a1), Math.max(a0, a1));
        ctx.closePath();
        ctx.fillStyle = 'rgba(' + sweepRGB + ',' + (0.16 * (1 - i / 10)).toFixed(3) + ')';
        ctx.fill();
      }
      ctx.beginPath();
      ctx.moveTo(ox, oy);
      ctx.lineTo(ox + Math.cos(ang) * R, oy + Math.sin(ang) * R);
      ctx.strokeStyle = 'rgba(' + sweepRGB + ',.55)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // what the scanner sees, the last few scans fading; the newest just behind the beam is
    // lit. Every point is drawn alike - points close to the vehicle get no highlight of their
    // own (2026-10-15: they piled up into a red blob in front of the bumper).
    var ink = color('--point');
    trail.forEach(function (scan, k) {
      var age = trail.length - 1 - k;
      var alpha = active ? 1 - age / TRAIL : 0.25;
      ctx.globalAlpha = Math.max(0.08, alpha);
      ctx.fillStyle = ink;
      // one path for the scan, one for the points the beam has just passed
      var dim = new Path2D(), lit = new Path2D();
      scan.points.concat(scan.near).forEach(function (p) {
        if (Math.hypot(p[0] - SCANNER_X, p[1]) > rangeM) return;  // only out to the radar's range
        var x = sx(p[0], p[1]), y = sy(p[0], p[1]);
        var hit = age === 0 && active && !reduced &&
          Math.abs(Math.atan2(y - oy, x - ox) - ang) < 0.12;
        var path = hit ? lit : dim, r = hit ? DOT_LIT : DOT;
        path.moveTo(x + r, y);
        path.arc(x, y, r, 0, Math.PI * 2);
      });
      ctx.fill(dim);
      ctx.fillStyle = 'rgb(' + sweepRGB + ')';
      ctx.fill(lit);
    });
    ctx.globalAlpha = 1;
  }

  var lastFrame = 0;
  function frame(t) {
    if (!document.hidden && t - lastFrame >= FPS_MS) {
      lastFrame = t;
      drawLive(t);
    }
    if (!reduced) requestAnimationFrame(frame);
  }
  window.addEventListener('resize', function () { drawStatic(); drawLive(performance.now()); });

  function setStatus(s, sentence) {
    status = s;
    statusBox.dataset.status = s;
    live.dataset.status = s;
    $('d-sentence').textContent = sentence;
  }

  function show(d) {
    setStatus(d.status, d.sentence);
    trail.push({ points: d.points || [], near: d.near_points || [] });
    while (trail.length > TRAIL) trail.shift();
    if (reduced) drawLive(0);
  }

  function poll() {
    fetch('/api/demo', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { lastOk = Date.now(); show(d); })
      .catch(function () {
        if (Date.now() - lastOk > STALE_MS) {
          setStatus('standby', 'Standing by for the next demonstration');
          trail = [];
          if (reduced) drawLive(0);
        }
      })
      .then(function () { setTimeout(poll, POLL_MS); });
  }
  setStatus('standby', 'Standing by for the next demonstration');
  drawStatic();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(drawStatic);
  if (reduced) drawLive(0); else requestAnimationFrame(frame);
  poll();

  // ---- feature slides ----
  var track = $('d-track');
  var slides = Array.prototype.slice.call(document.querySelectorAll('.d-slide'));
  var dots = Array.prototype.slice.call(document.querySelectorAll('#d-dots button'));
  var bar = $('d-progress');
  var rotateMs = (Number($('d-cards').dataset.rotate) || 8) * 1000;
  var idx = 0, timer = null;

  function progress(ms) {
    // restart the bar's fill animation for this slide, in its colour
    bar.className = '';
    bar.style.background = slides.length ? getComputedStyle(slides[idx]).getPropertyValue('--accent') : '';
    void bar.offsetWidth;  // reflow, so the animation starts over
    bar.style.animationDuration = ms + 'ms';
    bar.className = 'run';
  }
  function go(i) {
    if (!slides.length) return;
    idx = (i + slides.length) % slides.length;
    track.style.transform = 'translateX(' + (-100 * idx) + '%)';
    dots.forEach(function (d, k) { d.classList.toggle('on', k === idx); });
  }
  function schedule(ms) {
    clearTimeout(timer);
    progress(ms);  // after a tap the bar fills over the whole 30 s pause
    timer = setTimeout(function () { go(idx + 1); schedule(rotateMs); }, ms);
  }
  function tapped(i) { go(i); schedule(PAUSE_MS); }

  dots.forEach(function (d, k) {
    d.addEventListener('click', function (e) { e.stopPropagation(); tapped(k); });
  });
  // tap = next; a horizontal swipe = next / previous
  var downX = null;
  var cards = $('d-cards');
  cards.addEventListener('pointerdown', function (e) { downX = e.clientX; });
  cards.addEventListener('pointerup', function (e) {
    if (downX === null) return;
    var dx = e.clientX - downX;
    downX = null;
    if (Math.abs(dx) > 50) tapped(idx + (dx < 0 ? 1 : -1));
    else tapped(idx + 1);
  });
  go(0);
  schedule(rotateMs);

  // ---- reload: like Ctrl+Shift+R (the panel has no keyboard). Re-download the CSS
  // and JS into the cache first, so a software update shows. ----
  $('d-reload').addEventListener('click', function () {
    var urls = Array.prototype.map.call(
      document.querySelectorAll('link[rel="stylesheet"][href], script[src]'),
      function (e) { return e.href || e.src; });
    Promise.all(urls.map(function (u) {
      return fetch(u, { cache: 'reload' }).catch(function () {});
    })).then(function () { location.reload(); });
  });

  // ---- the corner ✕ goes to the operator's Home ----
  $('d-exit').addEventListener('click', function () { location.href = '/home'; });
})();
