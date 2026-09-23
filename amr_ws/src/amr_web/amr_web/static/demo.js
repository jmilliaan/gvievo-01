// The DEMO page (templates/demo.html). Read-only: the one request it makes is
// GET /api/demo, whose every word is decided server-side in demo.py.
(function () {
  'use strict';

  var POLL_MS = 1000;
  var STALE_MS = 5000;      // no answer this long: the live side says "standing by"
  var HOLD_MS = 2000;       // press-and-hold on the corner button to leave
  var PAUSE_MS = 30000;     // a visitor who taps a card gets to read it

  var $ = function (id) { return document.getElementById(id); };
  var statusBox = document.querySelector('.d-status');
  var lastOk = 0;

  function show(d) {
    statusBox.dataset.status = d.status;
    $('d-sentence').textContent = d.sentence;
    $('d-speed').textContent = Number(d.speed_mps).toFixed(2);
    $('d-dist').textContent = Math.round(d.distance_m);
    $('d-stops').textContent = d.safety_stops;
    $('d-mode').textContent = d.mode;
  }

  function poll() {
    fetch('/api/demo', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { lastOk = Date.now(); show(d); })
      .catch(function () {
        if (Date.now() - lastOk > STALE_MS) {
          statusBox.dataset.status = 'standby';
          $('d-sentence').textContent = 'Standing by for the next demonstration';
          $('d-speed').textContent = '0.00';
        }
      })
      .then(function () { setTimeout(poll, POLL_MS); });
  }
  poll();

  // ---- story cards ----
  var cards = Array.prototype.slice.call(document.querySelectorAll('.d-card'));
  var dots = Array.prototype.slice.call(document.querySelectorAll('#d-dots button'));
  var rotateMs = (Number($('d-cards').dataset.rotate) || 8) * 1000;
  var idx = 0, timer = null;

  function go(i) {
    if (!cards.length) return;
    idx = (i + cards.length) % cards.length;
    cards.forEach(function (c, k) { c.classList.toggle('on', k === idx); });
    dots.forEach(function (d, k) { d.classList.toggle('on', k === idx); });
  }
  function schedule(ms) {
    clearTimeout(timer);
    timer = setTimeout(function () { go(idx + 1); schedule(rotateMs); }, ms);
  }
  cards.forEach(function (c) {
    c.addEventListener('click', function () { go(idx + 1); schedule(PAUSE_MS); });
  });
  dots.forEach(function (d, k) {
    d.addEventListener('click', function () { go(k); schedule(PAUSE_MS); });
  });
  schedule(rotateMs);

  // ---- hold to leave: a tap does nothing, 2 s held goes back to Home ----
  var exit = $('d-exit'), held = null;
  function start(e) {
    e.preventDefault();
    exit.classList.add('holding');
    held = setTimeout(function () { location.href = '/home'; }, HOLD_MS);
  }
  function cancel() {
    clearTimeout(held);
    held = null;
    exit.classList.remove('holding');
  }
  exit.addEventListener('pointerdown', start);
  ['pointerup', 'pointerleave', 'pointercancel'].forEach(function (t) { exit.addEventListener(t, cancel); });
  exit.addEventListener('contextmenu', function (e) { e.preventDefault(); });
})();
