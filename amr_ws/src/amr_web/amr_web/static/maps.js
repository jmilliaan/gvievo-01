// Maps page: survey session controls (asynchronous supervisor operations) and the saved revisions.
const $ = id => document.getElementById(id);
const busy = (on) => ['btn-survey-start', 'btn-survey-returned', 'btn-survey-save', 'btn-survey-abort'].forEach(id => $(id).disabled = on);
function op(path, body) { busy(true); return operation(path, body, () => { busy(false); loadMaps(); }); }
$('btn-survey-start').onclick = () => op('/api/survey/start', { map_id: $('survey-map-id').value.trim(), description: $('survey-desc').value.trim() });
$('btn-survey-returned').onclick = () => op('/api/survey/returned');
$('btn-survey-save').onclick = () => op('/api/survey/save', { note: $('survey-note').value.trim() });
$('btn-survey-abort').onclick = () => op('/api/survey/abort');
onState(st => {
  const mode = st.mode;
  const m = st.mapping;
  if (!mode) { $('survey-state').textContent = 'no supervisor'; return; }
  if (mode.mode_name !== 'MAPPING') {
    $('survey-state').textContent = `mode ${mode.mode_name}${mode.phase ? ' · ' + mode.phase : ''}` +
      (mode.last_survey_map_id ? `\nlast saved survey: ${mode.last_survey_map_id} rev${mode.last_survey_revision} — use it from the Run page` : '') +
      (mode.reason ? `\n${mode.reason}` : '');
    $('closure').textContent = '';
    return;
  }
  if (!m) { $('survey-state').textContent = 'MAPPING — waiting for the session coordinator'; return; }
  $('survey-state').textContent = `${m.state_name}  ${m.map_id ? 'map ' + m.map_id : ''}${m.revision ? ' rev' + m.revision : ''}\n${m.message}`;
  $('closure').textContent = m.closure_available ? `closure as estimated: dx ${m.closure_dx_m.toFixed(3)} m, dy ${m.closure_dy_m.toFixed(3)} m, dyaw ${(m.closure_dyaw_rad * 180 / Math.PI).toFixed(2)}°  — review seams before saving` : '';
});
async function loadMaps() {
  const { data } = await apiGet('/api/maps');
  if (!data.length) { $('maps-list').textContent = 'no saved maps yet'; return; }
  $('maps-list').innerHTML = data.map(m => `<h3>${esc(m.map_id)}</h3><table><tr><th>rev</th><th>created</th><th>size</th><th>closure review</th><th>routes</th><th>bundle</th></tr>` +
    m.revisions.map(r => r.error ? `<tr><td>${esc(r.revision)}</td><td colspan=5 style="color:#e74c3c">${esc(r.error)}</td></tr>` :
      `<tr><td>${esc(r.revision)}</td><td>${esc(r.created)}</td><td>${esc(r.width)}×${esc(r.height)} @ ${esc(r.resolution)} m</td><td>${r.review ? `dx ${(+r.review.dx_m).toFixed(2)} dy ${(+r.review.dy_m).toFixed(2)} dyaw ${(+r.review.dyaw_rad * 180 / Math.PI).toFixed(1)}° ${esc(r.review.note)}` : ''}</td><td>${Object.entries(r.routes || {}).map(([k, v]) => `${esc(k)} rev${esc(v.join(','))}`).join('; ')}</td><td><code>${esc(String(r.sha256).slice(0, 12))}</code></td></tr>`).join('') + '</table>').join('');
}
loadMaps();

// live occupancy + pose while surveying, and the shared jog pad next to it
const liveView = new MapView(document.getElementById('live-canvas'));
liveOverlay(liveView);
pollLive(liveView, { map: true });
jogpad(document.getElementById('jog-maps'));
