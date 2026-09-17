// Live pose + scan overlay and the bounded pollers (unified plan §6.4).
// liveOverlay(view): draws the vehicle pose and the current scan in the view's
// frame only when the frames match; stale (> 1 s) data is drawn dimmed, and a
// generation mismatch draws nothing. pollLive(view, {map, hz}) polls
// /api/live/pose at 5 Hz and, if `map` is set, /api/live/map at 1 Hz, only
// while the page is visible - hidden pages request nothing.
let livePose = null;
function liveOverlay(view) {
  view.overlays.push((c, v) => {
    if (!livePose || !v.meta) return;
    const mode = lastState && lastState.mode;
    const gen = mode ? mode.generation : null;
    if (gen !== null && livePose.generation !== gen) return;
    // every map calls its frame "map": a saved map is only comparable if it is the active one (R12)
    if (v.meta.map_id !== undefined && !(mode && mode.active_map_id === v.meta.map_id && +mode.active_map_revision === +v.meta.revision)) return;
    const frame = v.meta.frame_id || 'map';
    const s = livePose.scan;
    if (s && s.frame === frame) v.points(s.points, s.age_s > 1.0 ? '#8b1a1a' : '#e74c3c');
    const p = livePose.pose;
    if (p && p.frame === frame) v.arrow(p.x, p.y, p.yaw, 0.6, p.age_s > 1.0 ? '#777' : '#2ecc71');
  });
}
function pollLive(view, opts) {
  const o = Object.assign({ map: false, poseHz: 5, mapHz: 1 }, opts || {});
  let tPose = 0, tMap = 0;
  async function tick() {
    if (!document.hidden) {
      const now = Date.now();
      if (now - tPose >= 1000 / o.poseHz) {
        tPose = now;
        const { status, data } = await apiGet('/api/live/pose');
        if (status === 200) { livePose = data; view.draw(); }
      }
      if (o.map && now - tMap >= 1000 / o.mapHz) {
        tMap = now;
        const { status, data } = await apiGet('/api/live/map');
        if (status === 200) { if (data.available) await view.loadLive(data); else if (view._liveSnapshot) view.clearLive(); }
      }
    }
    setTimeout(tick, 100);
  }
  tick();
}
