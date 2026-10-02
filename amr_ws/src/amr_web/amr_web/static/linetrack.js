// The MLS line strip (_line_track.html): Manual and Run tracked only, so the rail's
// shared amr.js does not reference ids other pages lack.
// LCP1..3 on a bar scaled to the profile's sensor_max_mm. Older than 1 s = no reading.
function lineTrack(t) {
  const box = document.getElementById('line-track');
  const live = !!t && t.age_s <= 1.0;
  box.classList.toggle('stale', !live);
  const max = (t && t.sensor_max_mm) || 100;
  document.getElementById('lt-min').textContent = `−${max}`;
  document.getElementById('lt-max').textContent = `+${max}`;
  document.getElementById('lt-status').textContent = !t ? 'no reading (drive_node not publishing)'
    : !live ? `stale ${t.age_s.toFixed(1)} s`
    : `${t.nlcp_label} · level ${t.track_level}/7 · ${t.line_good ? 'good' : 'weak'} · ${t.polarity}` + (t.marker ? ` · marker ${t.marker}` : '');
  box.querySelectorAll('.lt-dot').forEach(d => {
    const i = +d.dataset.i, on = live && t.valid[i];
    d.hidden = !on;
    if (on) d.style.left = `${50 + 50 * Math.max(-1, Math.min(1, t.lcp_mm[i] / max))}%`;
  });
  document.getElementById('lt-lcps').innerHTML = [0, 1, 2].map(i => {
    const on = live && t.valid[i];
    return `<span class="${on ? '' : 'muted'}">LCP${i + 1} <b>${on ? (t.lcp_mm[i] > 0 ? '+' : '') + t.lcp_mm[i] + ' mm' : '–'}</b></span>`;
  }).join('');
}
