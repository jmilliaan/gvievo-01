// Maps page: survey session controls and the list of saved revisions.
const $ = id => document.getElementById(id);
$('btn-survey-start').onclick = () => api('/api/survey/start', { map_id: $('survey-map-id').value.trim(), description: $('survey-desc').value.trim() }).then(r => log(r.data.message, r.status === 200 ? '' : 'err'));
$('btn-survey-returned').onclick = () => api('/api/survey/returned').then(r => log(r.data.message, r.status === 200 ? '' : 'err'));
$('btn-survey-save').onclick = () => api('/api/survey/save', { note: $('survey-note').value.trim() }).then(r => { log(r.data.message, r.status === 200 ? '' : 'err'); loadMaps(); });
$('btn-survey-abort').onclick = () => api('/api/survey/abort').then(r => log(r.data.message));
onState(st => {
  const m = st.mapping;
  if (!m) { $('survey-state').textContent = 'no mapping session (mapping.launch.py not running)'; return; }
  $('survey-state').textContent = `${m.state_name}  ${m.map_id ? 'map ' + m.map_id : ''}${m.revision ? ' rev' + m.revision : ''}\n${m.message}`;
  $('closure').textContent = m.closure_available ? `closure as estimated: dx ${m.closure_dx_m.toFixed(3)} m, dy ${m.closure_dy_m.toFixed(3)} m, dyaw ${(m.closure_dyaw_rad * 180 / Math.PI).toFixed(2)}°  — review seams in Foxglove before saving` : '';
});
async function loadMaps() {
  const { data } = await apiGet('/api/maps');
  if (!data.length) { $('maps-list').textContent = 'no saved maps yet'; return; }
  $('maps-list').innerHTML = data.map(m => `<h3>${m.map_id}</h3><table><tr><th>rev</th><th>created</th><th>size</th><th>closure review</th><th>routes</th><th>bundle</th></tr>` +
    m.revisions.map(r => r.error ? `<tr><td>${r.revision}</td><td colspan=5 style="color:#e74c3c">${r.error}</td></tr>` :
      `<tr><td>${r.revision}</td><td>${r.created}</td><td>${r.width}×${r.height} @ ${r.resolution} m</td><td>${r.review ? `dx ${(+r.review.dx_m).toFixed(2)} dy ${(+r.review.dy_m).toFixed(2)} dyaw ${(+r.review.dyaw_rad * 180 / Math.PI).toFixed(1)}° ${r.review.note || ''}` : ''}</td><td>${Object.entries(r.routes || {}).map(([k, v]) => `${k} rev${v.join(',')}`).join('; ')}</td><td><code>${r.sha256.slice(0, 12)}</code></td></tr>`).join('') + '</table>').join('');
}
loadMaps();
