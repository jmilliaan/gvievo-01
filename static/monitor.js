// Drive monitoring page. READ-ONLY: it has no controls and, deliberately, it
// does not claim the auto watchdog (no window.CLAIM_HEARTBEAT here). Leaving
// this page open on a second screen must never hold a run alive.
//
// Detail comes from /api/can, which never calls keepalive(). The shared rail at
// the left still comes from common.js's /api/state poll, without hb=1.

const NODE_ORDER = ['1', '2'];
const NODE_LABEL = {'1': 'left', '2': 'right'};

function cell(label, value, unit, state) {
  const cls = state === 'trip' ? ' bad' : (state === 'warn' ? ' warn' : '');
  return `<div class="tel${cls}"><span>${label}</span>`
       + `<b>${value}</b><i>${unit || '&nbsp;'}</i></div>`;
}

// A monitored object that has not been read yet is blank, not zero. The
// round-robin takes ~220 ms for a full sweep, so on load most of the table is
// legitimately empty and showing 0 would read as a real measurement.
function val(mon, node, key, digits) {
  const v = ((mon.nodes || {})[node] || {})[key];
  if (!v || v.value === null || v.value === undefined) return null;
  return {...v, shown: digits === undefined ? v.value : v.value.toFixed(digits)};
}

function group(el, mon, rows) {
  const html = NODE_ORDER.map(n => {
    const cells = rows.map(([key, label, digits, unit]) => {
      const v = val(mon, n, key, digits);
      return cell(label, v ? v.shown : '–', unit !== undefined ? unit
                                                               : (v ? v.unit : ''),
                  v ? v.state : 'ok');
    }).join('');
    return `<div class="mon-node"><h3>node ${n} · ${NODE_LABEL[n]}</h3>`
         + `<div class="tel-grid">${cells}</div></div>`;
  }).join('');
  document.getElementById(el).innerHTML = html;
}

function renderState(can, nodes, health) {
  const html = NODE_ORDER.map(n => {
    const t = (nodes || {})[n] || {};
    const flags = ((can.flags || {})[n]) || [];
    const hb = ((health.sources || {})['driver:' + n]) || {};
    const age = hb.age_s === null || hb.age_s === undefined
      ? '—' : hb.age_s.toFixed(2) + ' s';
    const flagHtml = flags.length
      ? flags.map(f => `<span class="chip ${f.level}" title="${f.note}">${f.name}</span>`).join('')
      : '<span class="chip">clear</span>';
    return `<div class="mon-node"><h3>node ${n} · ${NODE_LABEL[n]}</h3>`
         + `<div class="tel-grid">`
         + cell('CiA 402', t.state || '–', 'state')
         + cell('NMT', (can.nmt || {})[n] || '–', 'from heartbeat')
         + cell('Heartbeat', age, 'since last', hb.ok === false ? 'trip' : 'ok')
         + cell('Statusword', t.statusword === null || t.statusword === undefined
                ? '–' : '0x' + t.statusword.toString(16).toUpperCase().padStart(4, '0'), '6041h')
         + `</div><div class="chips">${flagHtml}</div></div>`;
  }).join('');
  document.getElementById('mon-state').innerHTML = html;
}

function renderAlarms(can) {
  const rows = NODE_ORDER
    .map(n => [n, (can.alarms || {})[n]])
    .filter(([, a]) => a && !a.cleared);
  const el = document.getElementById('mon-alarms');
  if (!rows.length) {
    el.innerHTML = '<div class="mon-none">no alarm reported since start-up'
                 + (can.emcy_seen ? ` · ${can.emcy_seen} EMCY frame(s) seen` : '')
                 + '</div>';
    return;
  }
  el.innerHTML = rows.map(([n, a]) =>
    `<div class="mon-alarm ${a.level}">`
    + `<b>${a.hex}</b> ${a.name}`
    + `<span class="mon-alarm-node">node ${n} · ${a.label}`
    + (a.tier ? ` · ${a.tier.toUpperCase()}` : '') + `</span>`
    + (a.note ? `<div class="mon-note">${a.note}</div>` : '')
    + (a.register_bits && a.register_bits.length
        ? `<div class="mon-note">error register: ${a.register_bits.join(', ')}</div>` : '')
    + `</div>`).join('');
}

async function pollCan() {
  try {
    const d = await apiGet('/api/can');
    const can = d.can || {};
    const mon = can.monitor || {nodes: {}};
    renderState(can, d.nodes, d.health || {});
    renderAlarms(can);
    group('mon-power', mon, [
      ['bus_v', 'Bus voltage', 1],
      ['inv_v', 'Inverter', 1],
      ['cur_a', 'Current', 3],
    ]);
    group('mon-thermal', mon, [
      ['drv_c', 'Driver', 1],
      ['mtr_c', 'Motor', 1],
    ]);
    group('mon-load', mon, [
      ['torque', 'Torque', 1],
      ['load', 'Load factor', 1],
      ['pos_dev', 'Position dev', 0, 'counts'],
      ['spd_dev', 'Speed dev', 0, 'counts'],
    ]);
    group('mon-raw', mon, [
      ['info', 'Information 407Bh', 0, 'raw'],
      ['comm_err', 'Comms error 4056h', 0, 'raw'],
    ]);
  } catch (e) {
    /* the shared rail already reports an unreachable server */
  }
}

// Slower than the control page: every value here is slow-moving, and the
// round-robin only completes a sweep every ~220 ms anyway.
setInterval(pollCan, 500);
pollCan();
