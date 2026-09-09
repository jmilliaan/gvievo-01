"""Route, repeated physical tags and speed changes exercised without hardware."""
import copy
import json
from unittest.mock import patch

from helpers import ROOT, check, sensor
import autopilot
import canworker
import config
import rfid
import route
import runlog


def frame(tag):
    data = bytearray(17)
    data[0] = 0xCF
    data[13:15] = bytes.fromhex(tag)
    return bytes(data)


def test_route_sequence():
    r = route.Route(config.ROUTE, config.HIGH_SPEED_MODE)
    check("startup is parked at 2 outbound", r.current.id == '2' and r.parked
          and r.direction == 'outbound')
    check("reads during dwell cannot advance", r.encounter('0010') is None)
    for lap in range(2):
        for origin, target, tag, direction, opposite in (
                ('2', '3', '0010', 'outbound', '0011'),
                ('3', '4', '0011', 'inbound', '0010'),
                ('4', '1', '0011', 'inbound', '0010'),
                ('1', '2', '0010', 'outbound', '0011')):
            r.depart()
            check(f"{origin}->{target} direction", r.direction == direction)
            check(f"{origin}->{target} ignores pass-through station", r.encounter(opposite) is None)
            entrance, exit_tag = ('0020', '0021') if direction == 'outbound' else ('0021', '0020')
            for segment in range(2):
                r.encounter(entrance)
                check(f"{origin} segment {segment}: high only on long legs",
                      r.high == (origin in ('2', '4')))
                r.encounter(entrance)
                r.encounter(exit_tag)
                check(f"{origin} segment {segment}: exit clears high", not r.high)
            arrived = r.encounter(tag)
            check(f"arrived at physical station {target}", arrived is not None
                  and arrived.id == target and r.parked and not r.high)
            check(f"{target} dwell ignores every further read", r.encounter(tag) is None)
        check("one lap counted at point 2", r.laps == lap + 1)


def test_encounters():
    now = [100.0]
    with patch('rfid.time.monotonic', side_effect=lambda: now[0]):
        link = rfid.RfidLink()
        link._absorb([frame('0010')])
        for _ in range(50):
            now[0] += 0.02
            link._absorb([frame('0010')])
        snap = link.snapshot(encounters=True)
        check("51 raw reads are one encounter", snap['tags_seen'] == 51
              and snap['encounter_seq'] == 1)
        now[0] += config.RFID_TAG_CLEAR_S + 0.01
        link._absorb([frame('0010')])
        check("same value after clearance is another physical encounter",
              link.snapshot()['encounter_seq'] == 2)
        link._absorb([frame('0020'), frame('0021'), frame('0011')])
        check("a batch preserves every different tag in order",
              [t for n, t in link.snapshot(encounters=True)['encounters']]
              == ['0010', '0010', '0020', '0021', '0011'])
        before = link.snapshot()['encounter_seq']
        link._drop()
        now[0] += 100
        link._absorb([frame('0011')])
        check("reconnect does not invent a departure", link.snapshot()['encounter_seq'] == before)
        check("reconnect discards the old queue", not link.snapshot(encounters=True)['encounters'])
        now[0] += config.RFID_TAG_CLEAR_S + 0.01
        link._absorb([frame('0011')])
        check("fresh clearance after reconnect rearms the same tag",
              link.snapshot()['encounter_seq'] == before + 1)


def test_controller_route():
    now = [100.0]
    real_log = runlog.RunLog
    with patch('canworker.time.monotonic', side_effect=lambda: now[0]), \
            patch('canworker.time.perf_counter', side_effect=lambda: now[0]), \
            patch('canworker.runlog.RunLog', side_effect=lambda: real_log(enabled=False)):
        c = canworker.Controller()
        c._rfid._connected = True
        c._rfid.carrier = lambda: True
        c._armed, c._mode = True, 'auto'
        c._do_auto_run(True, source='panel')

        def tick(tag=None, seconds=0.02, new_sensor=True):
            now[0] += seconds
            if tag:
                c._rfid._absorb([frame(tag)])
            c._sensor = dict(sensor(0), nlcp=2)
            c._sensor_last = now[0]
            if new_sensor:
                c._sensor_seen += 1
            return c._run_autopilot()

        tick('0010')
        check("initial point 2 read AFTER Start is not point 3", c._stop_hold is None)
        for _ in range(30):
            tick('0010')
        check("standing on departed tag never reparks", c._stop_hold is None)
        tick(seconds=config.RFID_TAG_CLEAR_S + 0.01)
        tick('0020', new_sensor=False)
        check("entry is processed even without a new sensor frame", c._route.high)
        tick('0021', new_sensor=False)
        check("exit is processed even without a new sensor frame", not c._route.high)
        tick('0011')
        check("outbound passes point 4 without stopping", c._stop_hold is None)
        tick('0010')
        check("point 3 starts a dwell in the same run", c._route.current.id == '3'
              and c._stop_hold == '0010' and c._auto_running)
        c._panel_start('auto')
        check("Start delay keeps arrival direction", c._route.direction == 'outbound')
        c._cancel_pending_start('test cancellation')
        check("cancelled Start cannot advance route", c._route.parked and c._route.next.id == '4')
        c._panel_start('auto')
        now[0] += config.AUTO_START_DELAY_S + 0.01
        c._pending_start()
        check("departure at 3 selects inbound", c._route.direction == 'inbound'
              and c._stop_hold is None)
        tick('0010')
        tick('0021')
        check("upper U-turn cannot enable high speed", not c._route.high)
        tick('0011')
        check("next arrival is point 4", c._route.current.id == '4' and c._route.parked)
        c._resume_from_stop()
        tick('0011')
        check("point 4 repeated read is not point 1", c._stop_hold is None)
        tick(seconds=config.RFID_TAG_CLEAR_S + 0.01)
        tick('0021')
        check("inbound entry enables high", c._route.high)
        c._hold_auto_run('test line loss')
        check("line hold preserves stage but clears high", c._route.current.id == '4'
              and c._route.next.id == '1' and not c._route.high)
        tick('0011')
        check("tag while holding cannot advance stage", c._route.current.id == '4')
        c._auto_hold = None
        tick(seconds=config.RFID_TAG_CLEAR_S + 0.01)
        tick('0011')
        check("same tag later arrives at 1", c._route.current.id == '1')
        c._end_auto_run('Reset', hard=True)
        saved = c._route.snapshot()
        # With software already disarmed, this path does no CAN transactions.
        c._armed = False
        c._do_disarm()
        check("disarm preserves route state", c._route.snapshot() == saved)
        c._armed, c._mode = True, 'auto'
        c._do_auto_run(True, source='panel')
        check("new run continues from 1 toward 2", c._route.direction == 'outbound'
              and c._route.next.id == '2')
        tick('0010')
        check("return to point 2 completes the lap", c._route.current.id == '2'
              and c._route.laps == 1 and c._stop_hold == '0010')


def test_recovery_and_overrun():
    c = canworker.Controller()
    c._log = runlog.RunLog(enabled=False)
    c._auto_running = True
    c._route.depart()
    c._route.high = True
    snap = dict(encounter_seq=1, generation=1, comms_ok=True, encounters=[(1, '0010')])
    c._scan_route(snap)
    check("reconnect clears high and drops pre-baseline encounters",
          not c._route.high and c._route.current.id == '2')
    c._route.high = True
    c._scan_route(dict(snap, comms_ok=False))
    check("reader loss clears high without advancing", not c._route.high
          and c._route.next.id == '3')
    c._scan_route(dict(snap, encounter_seq=258, encounters=[(3, '0020')]))
    check("missing encounter sequence stops rather than guessing position",
          not c._auto_running and c._fault is not None)


def test_high_speed_ramp():
    f = autopilot.LineFollower()
    f._v_rpm = config.AUTO_RPM
    states = []
    for _ in range(130):
        _, _, d = f.update(sensor(0), 0, .02, True, high=True)
        states.append(d)
    speeds = [d['v_base'] for d in states]
    check("normal to high reaches 2000", speeds[-1] == config.AUTO_RPM_HIGH)
    check("speed transition acceleration stays at derived rate",
          max((b-a)/.02 for a,b in zip(speeds, speeds[1:])) <= config.SPEED_SWITCH_RPM_S + 1e-6)
    check("transition retains jerk limiting", 0 < speeds[0] - config.AUTO_RPM < 500 * .02)
    check("high reports normal steering gain", states[-1]['k_used'] == config.K_RATIO)
    check("high is visible in diagnostics", states[-1]['speed_mode'] == 'high')
    for _ in range(130):
        f.update(sensor(0), 0, .02, True, high=False)
    check("exit returns exactly to normal", f._v_rpm == config.AUTO_RPM)
    for _ in range(35):
        f.update(sensor(0), 0, .02, True, high=True)
    intermediate = f._v_rpm
    for _ in range(130):
        f.update(sensor(0), 0, .02, True, high=False)
    check("exit during acceleration retargets without jumping",
          config.AUTO_RPM < intermediate < config.AUTO_RPM_HIGH
          and f._v_rpm == config.AUTO_RPM)
    for _ in range(160):
        _, _, d = f.update(sensor(0), 0, .02, True, slow=True, high=True)
    check("slow zone overrides high", d['speed_mode'] == 'slow'
          and f._v_rpm == config.AUTO_SLOW_RPM)
    f._v_rpm = config.AUTO_RPM_HIGH
    stop_rate = f.begin_measured_stop(.4)
    f.update(sensor(0), 0, .02, False, high=True)
    check("station stop retains its own deceleration", f._stop_rate == stop_rate)
    f.hard_stop()
    left, right, _ = f.update(sensor(0), 0, .02, False, high=True)
    check("hard stop overrides high target", left == right == 0)


def test_stale_sensor_at_high_speed():
    now = [100.0]
    with patch('canworker.time.monotonic', side_effect=lambda: now[0]), \
            patch('canworker.time.perf_counter', side_effect=lambda: now[0]):
        c = canworker.Controller()
        c._log = runlog.RunLog(enabled=False)
        c._rfid._connected = True
        c._rfid.carrier = lambda: True
        c._armed, c._mode, c._auto_running = True, 'auto', True
        c._route.depart()
        c._route.high = True
        c._follower._v_rpm = config.AUTO_RPM_HIGH
        c._sensor = sensor(0)
        c._sensor_seen, c._sensor_last = 1, now[0]
        c._run_autopilot()
        now[0] += config.SENSOR_TIMEOUT_S + .01
        target = c._run_autopilot()   # deliberately NO new frame
        check("stale frame cannot hold a high-speed command forever", target == (0, 0))
        check("sensor silence holds route and clears high", c._auto_hold is not None
              and not c._route.high and c._route.current.id == '2')


def test_route_validation():
    base = json.loads((ROOT / 'profiles/agv-01.json').read_text())
    def refused(name, mutate):
        doc = copy.deepcopy(base)
        mutate(doc)
        try:
            ns = config._parse(doc)
            config._derive(ns)
            config._validate(ns)
        except config.ConfigError:
            check(name, True)
        else:
            check(name, False)
    refused('duplicate station IDs refused', lambda d: d['route'][1].update(id='2'))
    refused('unknown station tag refused', lambda d: d['route'][1].update(tag='FFFF'))
    refused('bad route direction refused', lambda d: d['route'][1].update(direction='north'))
    refused('empty route refused', lambda d: d.update(route=[]))
    refused('ambiguous speed contacts refused', lambda d: d['high_speed_mode'][0].update(exit_tag='0020'))
    refused('speed and station tags cannot overlap', lambda d: d['high_speed_mode'][0].update(entry_tag='0010'))
    refused('duplicate qualified stops refused', lambda d: d['stop_until_start_button'].append(d['stop_until_start_button'][0]))
    refused('high below normal refused', lambda d: d['autopilot'].update(auto_rpm_high=900))
    refused('high above drive limit refused', lambda d: d['autopilot'].update(auto_rpm_high=5000))
    refused('zero transition time refused', lambda d: d['autopilot'].update(speed_switch_accel_decel_s=0))
    refused('excessive transition rate refused', lambda d: d['autopilot'].update(speed_switch_accel_decel_s=.1))
    refused('nonfinite high speed refused', lambda d: d['autopilot'].update(auto_rpm_high=float('nan')))
    refused('nonfinite clear interval refused', lambda d: d['rfid'].update(tag_clear_s=float('inf')))
    refused('legacy ignore window refused', lambda d: d['stop_until_start_button'][0].update(ignore_t=20))


TESTS = [test_route_sequence, test_encounters, test_controller_route,
         test_recovery_and_overrun, test_high_speed_ramp,
         test_stale_sensor_at_high_speed, test_route_validation]
