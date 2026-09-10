// Real DOM acceptance fixtures; run with browser_auto.py. No vehicle requests.
const browserChecks = [];
function expect(name, condition) { browserChecks.push({name, pass: !!condition}); }
function fixture(overrides = {}) {
  const s = structuredClone(window.TEST_STATE);
  Object.assign(s, {connected:true, armed:true, mode:'auto', auto_running:true});
  s.panel.fault = null; s.panel.starting_in = null;
  Object.assign(s.route, {station:'2', next_station:'3', parked:false, initial_assumption:false, guard_error:null});
  s.route_display.stopped = true;
  Object.assign(s, overrides);
  return s;
}
function displayed(id) { return document.getElementById(id).textContent; }
(async () => {
try {
  let s = fixture();
  showStation(s);
  expect('moving destination is primary', displayed('auto-point') === 'TO POINT 3');
  expect('direction prominent', displayed('auto-direction') === 'OUTBOUND');
  expect('sequence includes return boundary', document.querySelectorAll('#auto-sequence li').length === 5);
  expect('next station labelled', displayed('auto-sequence').includes('POINT 3 - NEXT'));
  for (const [station, next, direction] of [['2','3','outbound'],['3','4','inbound'],['4','1','inbound'],['1','2','outbound']]) {
    Object.assign(s.route, {station, next_station:next, travel_direction:direction});
    showStation(s);
    expect(`leg ${station}-${next} renders`, displayed('auto-point') === `TO POINT ${next}` && displayed('auto-direction') === direction.toUpperCase());
  }
  Object.assign(s.route, {station:'3', next_station:'4', travel_direction:'outbound', parked:true});
  s.route_display.next_departure_direction = 'inbound';
  s.route_display.stopped = false; showStation(s);
  expect('accepted tag is still stopping', displayed('auto-status') === 'STOPPING');
  s.route_display.stopped = null; showStation(s);
  expect('unknown feedback cannot claim dwell', displayed('auto-status') === 'STOP STATUS UNKNOWN');
  s.route_display.stopped = true; showStation(s);
  expect('fresh stopped feedback allows dwell', displayed('auto-status') === 'WAITING FOR START');
  expect('next departure direction separate', displayed('auto-direction') === 'OUTBOUND' && displayed('auto-next-direction').includes('INBOUND'));
  s.panel.starting_in = .4; showStation(s);
  expect('pending start preserves arrival direction', displayed('auto-status').startsWith('STARTING') && displayed('auto-direction') === 'OUTBOUND');
  s.panel.starting_in = null; showStation(s);
  expect('cancelled start returns to dwell', displayed('auto-status') === 'WAITING FOR START');
  s.auto_hold = 'line lost'; showStation(s);
  expect('hold overrides normal headline', displayed('auto-status') === 'HOLD' && displayed('auto-context') === 'line lost');
  s.auto_hold = null; s.mode = 'manual'; showStation(s);
  expect('manual is not travelling', displayed('auto-status') === 'MANUAL');
  s.mode = 'auto'; s.armed = false; s.auto_running = false; showStation(s);
  expect('disarm overrides dwell', displayed('auto-status') === 'DISARMED');
  s.route.guard_error = 'position lost'; showStation(s);
  expect('route fault overrides point confidence', displayed('auto-point') === 'POSITION UNKNOWN');
  s.route.guard_error = null; s.panel.fault = 'drive fault'; showStation(s);
  expect('controller fault dominates status', displayed('auto-status') === 'FAULT');
  s = fixture(); s.route.parked = true; s.route.initial_assumption = true; showStation(s);
  expect('boot position explicitly assumed', displayed('auto-status') === 'INITIAL POSITION ASSUMED');
  s = fixture(); s.rfid = {tag:'0010', last_tag:'0010', tag_age_s:.1, comms_ok:true, tags_seen:50, encounter_seq:1};
  s.route_display.last_encounter = {sequence:1, tag:'0010', action:'no route action', age_s:.1};
  showStation(s);
  expect('raw read never changes destination', displayed('auto-point') === 'TO POINT 3' && displayed('auto-encounter').includes('no route action'));
  expect('tag retains leading zeroes', displayed('auto-tag') === '0010');
  expect('recent read distinguished', displayed('auto-tag-label') === 'RECENT READ');
  s.rfid.tag = null; s.rfid.tag_age_s = 3; showStation(s);
  expect('expired read retained as history', displayed('auto-tag') === '0010' && displayed('auto-tag-label') === 'LAST READ');
  s.rfid.tag = '0010'; s.rfid.comms_ok = false; showStation(s);
  expect('disconnected reader cannot appear live', displayed('auto-tag-label') === 'LAST READ');
  showRfid(s.rfid, s.branch);
  expect('shared RFID renderer cannot overwrite Auto headline', displayed('auto-tag') === '0010');
  window.dispatchEvent(new Event('state-poll-error'));
  expect('failed poll marks state stale immediately', displayed('auto-status') === 'LIVE STATE UNAVAILABLE' && displayed('auto-tag-label').includes('STALE'));
  showStation(s);
  expect('fresh state restores summary', displayed('auto-status') === 'TRAVELLING');
  const ids = [...document.querySelectorAll('[id]')].map(e => e.id);
  expect('DOM IDs unique', new Set(ids).size === ids.length);
  expect('summary precedes diagnostics', !!(document.querySelector('.auto-summary').compareDocumentPosition(document.getElementById('p-err')) & Node.DOCUMENT_POSITION_FOLLOWING));
  expect('no motion requests', window.TEST_POSTS.length === 0);
  expect('no horizontal viewport overflow', document.documentElement.scrollWidth <= innerWidth);
  expect(`viewport width ${innerWidth}px matches requested ${window.TEST_WIDTH}px`, innerWidth === window.TEST_WIDTH);
  s.rfid.comms_ok = true; showStation(s);

  // Lap count is its own fact: the trailing 2 is a return boundary, not a stop.
  s = fixture(); s.route.laps = 3; showStation(s);
  expect('completed laps shown separately', displayed('auto-lap') === 'Completed laps: 3');
  expect('return boundary is not a fifth station', displayed('auto-sequence').includes('POINT 2 (RETURN)')
         && document.querySelectorAll('#auto-sequence li').length === 5);
  Object.assign(s.route, {station:'1', next_station:'2', travel_direction:'outbound'}); showStation(s);
  expect('return boundary carries NEXT on the final leg',
         [...document.querySelectorAll('#auto-sequence li')].pop().textContent === 'POINT 2 (RETURN) - NEXT');
  expect('first sequence entry is not also NEXT',
         document.querySelector('#auto-sequence li').textContent === 'POINT 2');

  // Junction order and reader health survived the summary rewrite.
  s = fixture(); s.branch = {intent:'left', set_by:'0030', slow:true}; showStation(s);
  expect('branch order still visible on auto', displayed('auto-branch') === 'left'
         && displayed('auto-branch-by').includes('tag 0030') && displayed('auto-branch-by').includes('SLOW'));
  s.rfid = {comms_ok:false, connected:true, enabled:true, silent:true, tags_seen:7, encounter_seq:2};
  showStation(s);
  expect('silent reader is not just "disconnected"', displayed('auto-reader-link') === 'silent'
         && displayed('auto-reader').includes('silent'));
  expect('raw and encounter counts stay in diagnostics', displayed('auto-rfid-count') === '7 · 2');
  s.rfid = {comms_ok:false, connected:true, enabled:true, carrier:false}; showStation(s);
  expect('cable loss named distinctly', displayed('auto-reader-link') === 'NO CABLE');

  // Reload mid-leg: the polling path ALONE must reproduce server state, with
  // no fixture call. Everything below here awaits, so polls may interleave.
  Object.assign(window.TEST_STATE, {connected:true, armed:true, mode:'auto', auto_running:true});
  window.TEST_STATE.panel.fault = null; window.TEST_STATE.panel.starting_in = null;
  Object.assign(window.TEST_STATE.route, {station:'4', next_station:'1', travel_direction:'inbound',
                                          parked:false, initial_assumption:false, guard_error:null, laps:1});
  await new Promise(done => setTimeout(done, 800));
  expect('reload mid-leg reproduces server state from polling alone',
         displayed('auto-point') === 'TO POINT 1' && displayed('auto-direction') === 'INBOUND'
         && displayed('auto-status') === 'TRAVELLING' && displayed('auto-lap') === 'Completed laps: 1');
  expect('live polling does not mark fresh state stale',
         !document.querySelector('.auto-summary').classList.contains('is-stale'));
  expect('polling issues no motion requests', window.TEST_POSTS.length === 0);
} catch (error) { browserChecks.push({name: String(error.stack || error), pass:false}); }
const output = document.createElement('pre'); output.id = 'browser-results'; output.textContent = JSON.stringify(browserChecks); output.hidden = true; document.body.appendChild(output);
})();
