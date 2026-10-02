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

// RFID: the reader link (2 Hz heartbeat) and the last tag passes, newest first. The newest
// is lit for RF_FRESH_S so a pass is visible while driving. Missing data is not an error:
// the offline demo server has no reader.
const RF_FRESH_S = 3.0;
function rfidTags(r) {
  const box = document.querySelector('.lt-rfid');
  if (!box) return;
  const link = r && r.link, tags = (r && r.tags) || [];
  const up = !!link && link.age_s <= 2.0 && link.comms_ok;
  box.classList.toggle('down', !up);
  const last = tags[0];
  document.getElementById('rf-status').textContent = !link ? 'no reader data (rfid_node not publishing)'
    : link.age_s > 2.0 ? `reader silent ${link.age_s.toFixed(1)} s`
    : !link.comms_ok ? 'reader link down'
    : last ? `link ok · last ${last.tag} ${ago(last.age_s)} · ${link.seq} read` : `link ok · no tag read yet`;
  document.getElementById('rf-tags').innerHTML = tags.length
    ? tags.map((t, k) => `<span class="rf-tag${k === 0 && t.age_s <= RF_FRESH_S ? ' fresh' : ''}" title="pass #${t.seq}"><b>${esc(t.tag)}</b> ${clock(t.wall)}</span>`).join('')
    : '<span class="none">pass a tag under the reader</span>';
}
function ago(s) { return s < 60 ? `${Math.round(s)} s ago` : `${Math.round(s / 60)} min ago`; }
function clock(wall) { const d = new Date(wall * 1000); return d.toTimeString().slice(0, 8); }
