"""Synthetic commissioning limits only; none of these distances describe the site."""
import copy
import builtins
import json
import threading
import types
from unittest.mock import patch

from helpers import ROOT, check, sensor
import canworker
import config
import events
import kinematics
import route
import runlog


def limits():
    return dict(enabled=True,
                legs=[dict(from_station=r['id'], min_m=2.0, max_m=5.0)
                      for r in config.ROUTE],
                high_speed_max_m=dict(outbound=1.0, inbound=1.0),
                station_decel_limit_rpm_s=1600.0)


def make_controller(now):
    c = canworker.Controller()
    c._log = runlog.RunLog(enabled=False)
    c._route = route.Route(config.ROUTE, config.HIGH_SPEED_MODE, limits())
    c._rfid._connected = True
    c._rfid.carrier = lambda: True
    set_feedback(c, now, 1000, 1000)
    c._depart_route()
    c._auto_running = True
    return c


def set_feedback(c, now, left, right):
    for nid, rpm in ((config.LEFT, left), (config.RIGHT, right)):
        c._telemetry[nid]['rpm'] = rpm
        c._rpm_seen[nid] = now


def test_guarded_arrivals():
    r = route.Route(config.ROUTE, config.HIGH_SPEED_MODE, limits())
    r.depart()
    r.advance(1.0)
    check('too-early equal-value station read rejected', r.encounter('0010') is None
          and r.current.id == '2' and 'early tag' in r.notice)
    r.advance(1.0)
    check('arrival at minimum accepted', r.encounter('0010').id == '3')
    r.depart()
    check('genuine departure resets estimated leg distance', r.distance_m == 0)
    r.advance(3.0)
    r.clear_speed()
    r.depart()
    check('resuming mid-leg preserves estimated distance', r.distance_m == 3.0)
    check('next station accepted inside window', r.encounter('0011').id == '4')

    r = route.Route(config.ROUTE, config.HIGH_SPEED_MODE, limits())
    r.depart()
    r.advance(4.0)
    r.encounter('0011')  # station 3 was missed; wrong-value stations pass through
    try:
        r.advance(1.01)
    except route.RouteError as exc:
        check('missed station faults before later equal-valued tag', 'expected station 3' in str(exc))
    else:
        check('missed station faults before later equal-valued tag', False)
    check('later point 2 cannot masquerade as point 3 after fault',
          r.encounter('0010') is None and r.current.id == '2')
    try:
        r.depart()
    except route.RouteError:
        check('position fault blocks restart of route in same process', True)
    else:
        check('position fault blocks restart of route in same process', False)


def test_zone_limit_and_event_edges():
    for index, direction, entry, exit_tag in ((0, 'outbound', '0020', '0021'),
                                               (2, 'inbound', '0021', '0020')):
        r = route.Route(config.ROUTE, config.HIGH_SPEED_MODE, limits())
        r.index = index
        r.depart()
        r.encounter(entry)
        r.advance(.6)
        r.encounter(entry)
        check(f'{direction}: repeated entry does not reset distance', r.zone_distance_m == .6)
        notice = r.advance(.4)
        check(f'{direction}: missed exit returns to normal at limit', bool(notice) and not r.high)
        check(f'{direction}: expiry emits only once', r.advance(.1) is None)
        r.clear_speed()
        r.depart()  # Reset/Start mid-leg must not clear expiry
        r.encounter(entry)
        check(f'{direction}: entry cannot bypass expired zone', not r.high)
        r.encounter(exit_tag)
        r.encounter(entry)
        check(f'{direction}: exit rearms next segment', r.high and r.zone_distance_m == 0)

    events.clear()
    now = [100.0]
    with patch('canworker.time.monotonic', side_effect=lambda: now[0]):
        c = make_controller(now[0])
        c._route.encounter('0020')
        c._route.zone_distance_m = .99
        for _ in range(80):
            now[0] += .02
            set_feedback(c, now[0], 2000, 2000)
            c._update_route_distance()
        notices = [e for e in events.since(0)[1] if 'high-speed distance exceeded' in e['msg']]
        check('controller logs zone timeout once across repeated scans', len(notices) == 1)
    events.clear()


def test_distance_feedback_and_failures():
    now = [100.0]
    with patch('canworker.time.monotonic', side_effect=lambda: now[0]), \
            patch('canworker.time.perf_counter', side_effect=lambda: now[0]):
        c = make_controller(now[0])
        now[0] += .2
        set_feedback(c, now[0], 1000, 2000)
        c._update_route_distance()
        expected = abs(kinematics.wheels_to_body(1000, 2000)[0]) * .2
        check('distance uses mean wheel feedback, not cruise target',
              abs(c._route.distance_m - expected) < 1e-9)
        before = c._route.distance_m
        now[0] += .2
        set_feedback(c, now[0], 0, 0)
        c._update_route_distance()
        check('standing vehicle accrues no distance', c._route.distance_m == before)
        now[0] += .02
        set_feedback(c, now[0], 1000, 1000)
        c._rpm_seen[config.RIGHT] = now[0] - config.DRIVER_TIMEOUT_S - .01
        c._target = (1000, 1000)
        c._update_route_distance()
        check('one stale wheel faults and zeros target', not c._auto_running
              and c._target == (0, 0) and c._route.guard_error is not None)
        set_feedback(c, now[0], 0, 0)
        c._fault = None  # acknowledging the operator fault cannot restore position
        try:
            c._depart_route()
        except route.RouteError:
            check('Reset cannot erase lost position confidence', True)
        else:
            check('Reset cannot erase lost position confidence', False)

        c = make_controller(now[0])
        c._route.distance_m = 4.999
        now[0] += .02
        set_feedback(c, now[0], 2000, 2000)
        c._sensor = sensor(0)
        c._sensor_last = now[0]
        c._sensor_seen = c._auto_seen = 1
        c._target = (2000, 2000)
        target = c._run_autopilot()
        check('distance fault precedes repeated MLS frame return', target == (0, 0)
              and not c._auto_running and c._route.current.id == '2')

        c = make_controller(now[0])
        now[0] += config.DRIVER_TIMEOUT_S + .01
        set_feedback(c, now[0], 1000, 1000)
        c._update_route_distance()
        check('long control gap faults even with newly refreshed feedback', bool(c._route.guard_error))

        c = make_controller(now[0])
        snap = dict(encounter_seq=1, generation=1, comms_ok=True,
                    encounters=[(1, '0010')])
        c._scan_route(snap)
        check('reconnect on station faults without consuming arrival', not c._auto_running
              and c._route.current.id == '2' and 'RFID continuity' in c._route.guard_error)
        c._scan_route(snap)
        check('repeated reconnect scan cannot advance route', c._route.current.id == '2')

        c = make_controller(now[0])
        c._scan_route(dict(encounter_seq=0, generation=0, comms_ok=False, encounters=[]))
        check('RFID disconnection faults without waiting for reconnect', not c._auto_running)

        c = make_controller(now[0])
        with patch.object(config, 'STOP_TAGS', {}):
            c._begin_station_stop('0010')
        check('missing stop rule produces fault rather than exception',
              not c._auto_running and 'missing stop rule' in c._fault)
    events.clear()


def test_guard_configuration():
    base = json.loads((ROOT / 'profiles/agv-01.json').read_text())
    base['route_guard'] = limits()
    check('fully specified synthetic limits load', config._parse(base)['ROUTE_GUARD']['enabled'])
    ns = config._parse(base)
    config._derive(ns)
    check('permitted high-speed stop rate passes derived validation', ns['ROUTE_GUARD']['enabled'])
    def refused(name, mutate):
        doc = copy.deepcopy(base)
        mutate(doc['route_guard'])
        try:
            ns = config._parse(doc)
            config._derive(ns)
        except config.ConfigError:
            check(name, True)
        else:
            check(name, False)
    refused('enabled guard rejects unknown measurements', lambda g: g['legs'][0].update(min_m=None))
    refused('guard rejects inverted arrival window', lambda g: g['legs'][0].update(min_m=6))
    refused('guard rejects missing route leg', lambda g: g['legs'].pop())
    refused('guard rejects duplicate leg ID', lambda g: g['legs'][0].update(from_station='3'))
    refused('guard rejects negative zone length', lambda g: g['high_speed_max_m'].update(inbound=-1))
    refused('guard rejects nonfinite zone length', lambda g: g['high_speed_max_m'].update(outbound=float('nan')))
    refused('guard rejects unknown settings', lambda g: g.update(typo=True))
    refused('guard rejects high-speed stop above measured deceleration limit',
            lambda g: g.update(station_decel_limit_rpm_s=500))
    refused('guard rejects deceleration above drive configuration',
            lambda g: g.update(station_decel_limit_rpm_s=4000))
    import server
    data = server.app.test_client().get('/api/config').get_json()
    check('API exposes disabled guard and unmeasured limits honestly',
          not data['route_guard']['enabled']
          and data['route_guard']['legs'][0]['min_m'] is None)


def test_guarded_start_and_arrival_stop():
    now = [100.0]
    with patch('canworker.time.monotonic', side_effect=lambda: now[0]):
        c = make_controller(now[0])
        c._route.advance(2.0)
        c._route.encounter('0010')
        c._stop_hold = '0010'
        c._auto_start_at = now[0]
        c._rpm_seen[config.RIGHT] = None
        c._pending_start()
        check('station Start refuses stale feedback without thread exception',
              c._route.parked and c._stop_hold == '0010'
              and 'fresh speed feedback' in c._fault)
        c = make_controller(now[0])
        c._route.advance(2.0)
        c._route.encounter('0020')
        c._follower._v_rpm = config.AUTO_RPM_HIGH
        c._departure_tag = None
        c._scan_route(dict(encounter_seq=1, generation=0, comms_ok=True,
                           encounters=[(1, '0010')]))
        expected = config.AUTO_RPM_HIGH ** 2 * config.MPS_PER_RPM / .8
        check('station reached with high latch clears high and uses approach speed',
              c._route.current.id == '3' and c._stop_hold == '0010'
              and not c._route.high and abs(c._follower._stop_rate - expected) < 1e-9)
        check('guarded approach rate fits the configured measured limit',
              c._follower._stop_rate <= c._route.guard['station_decel_limit_rpm_s'])
        c._auto_running = False
        before = c._route.distance_m
        now[0] += 1
        set_feedback(c, now[0], 0, 0)
        c._update_route_distance()
        check('station dwell and stopped run do not accrue distance', c._route.distance_m == before)
    events.clear()


def test_runner_fails_on_thread_exception():
    import run_all
    def fail_in_thread():
        raise RuntimeError('synthetic thread failure')
    def test_fn():
        worker = threading.Thread(target=fail_in_thread)
        worker.start()
        worker.join()
    fake = types.SimpleNamespace(TESTS=[test_fn])
    import helpers
    with patch.object(run_all, 'MODULES', ['synthetic']), \
            patch.object(run_all.importlib, 'import_module', return_value=fake), \
            patch.object(run_all, 'EXPECTED_CHECKS', helpers.CHECKS[0]), \
            patch.object(helpers, 'FAIL', []), \
            patch.object(threading, 'excepthook', lambda args: None), \
            patch.object(builtins, 'print'):
        result = run_all.main()
    check('runner exits nonzero for uncaught worker-thread exception', result == 1)


TESTS = [test_guarded_arrivals, test_zone_limit_and_event_edges,
         test_distance_feedback_and_failures, test_guard_configuration,
         test_guarded_start_and_arrival_stop, test_runner_fails_on_thread_exception]
