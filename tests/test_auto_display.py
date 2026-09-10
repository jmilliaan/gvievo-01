"""Display metadata must describe controller decisions, not raw RFID guesses."""
from unittest.mock import patch
from helpers import check
from test_route_guard import limits
import canworker
import config
import route
import runlog


def test_display_metadata():
    now = [100.0]
    with patch('canworker.time.monotonic', side_effect=lambda: now[0]):
        c = canworker.Controller()
        c._log = runlog.RunLog(enabled=False)
        s = c.snapshot()
        check('startup is explicitly an assumed position', s['route']['initial_assumption'])
        check('display sequence comes from profile', s['route_display']['sequence'] == ['2', '3', '4', '1'])
        check('missing drive status cannot prove stopped', s['route_display']['stopped'] is None)
        for n in (config.LEFT, config.RIGHT):
            c._telemetry[n]['speed_zero'] = True
            c._status_seen[n] = now[0]
        check('fresh stopped bits prove stopped display state', c.snapshot()['route_display']['stopped'] is True)
        c._telemetry[config.RIGHT]['speed_zero'] = False
        check('one moving wheel prevents dwell wording', c.snapshot()['route_display']['stopped'] is False)
        now[0] += config.DRIVER_TIMEOUT_S + .01
        check('old status cannot prove stopped or moving', c.snapshot()['route_display']['stopped'] is None)
        c._auto_running = True
        c._route.depart()
        c._departure_tag = '0010'
        c._departure_at = now[0]
        def read(seq, tag):
            c._scan_route(dict(encounter_seq=seq, generation=0, comms_ok=True,
                               encounters=[(seq, tag)], tag_age_s=0))
            return c.snapshot()['route_display']['last_encounter']
        e = read(1, '0010')
        check('departed-tag suppression is structured', e['action'] == 'suppressed' and e['station'] is None)
        e = read(2, '0020')
        check('high selection is a controller outcome', e['action'] == 'high selected')
        e = read(3, '0021')
        check('normal selection is a controller outcome', e['action'] == 'normal selected')
        e = read(4, '0011')
        check('pass-through read does not claim arrival', e['action'] == 'no route action' and e['station'] is None)
        e = read(5, '0010')
        check('accepted tag names physical station', e['action'] == 'station accepted' and e['station'] == '3')
        check('first arrival clears initial assumption', not c.snapshot()['route']['initial_assumption'])
        check('station 3 displays next departure direction separately', c.snapshot()['route_display']['next_departure_direction'] == 'inbound')
        now[0] += 1
        check('processed encounter age survives later polls', c.snapshot()['route_display']['last_encounter']['age_s'] == 1)
        e = read(6, '0011')
        check('held route outcome does not pretend to be an arrival', e['action'] == 'suppressed')
        c._scan_route(dict(encounter_seq=6, generation=1, comms_ok=True, encounters=[]))
        check('reconnect clears old processed outcome', c.snapshot()['route_display']['last_encounter'] is None)


def test_batched_and_rejected_outcomes():
    """One scan can carry several encounters; the record must not blur them."""
    now = [200.0]
    with patch('canworker.time.monotonic', side_effect=lambda: now[0]):
        c = canworker.Controller()
        c._log = runlog.RunLog(enabled=False)
        c._route = route.Route(config.ROUTE, config.HIGH_SPEED_MODE, limits())
        c._auto_running = True
        c._route.depart()

        def read(*pairs):
            last = pairs[-1][0]
            return c._scan_route(dict(encounter_seq=last, generation=0, comms_ok=True,
                                      tag_age_s=0, encounters=list(pairs)))

        check('restart shows point 2 outbound before any read',
              c.snapshot()['route']['station'] == '2'
              and c.snapshot()['route']['travel_direction'] == 'outbound')

        tags = read((1, '0020'), (2, '0011'), (3, '0021'))
        d = c.snapshot()['route_display']
        check('every batched tag still reaches the ladder exactly once',
              tags == ['0020', '0011', '0021'])
        check('batch reports the LAST processed encounter, not the first',
              d['last_encounter']['sequence'] == 3 and d['last_encounter']['tag'] == '0021')
        check('batched pass-through never claims arrival',
              d['last_encounter']['station'] is None and c.snapshot()['route']['station'] == '2')

        e = read((4, '0011'))[0] and c.snapshot()['route_display']['last_encounter']
        check('repeated pass-through read stays a non-event',
              e['action'] == 'no route action' and e['sequence'] == 4)

        c._route.advance(1.0)                       # short of the 2.0 m minimum
        read((5, '0010'))
        e = c.snapshot()['route_display']['last_encounter']
        check('early equal-valued read is rejected, not an arrival',
              e['action'] == 'early arrival rejected' and e['station'] is None)
        check('a rejected read leaves the route stage alone',
              c.snapshot()['route']['station'] == '2' and not c.snapshot()['route']['parked'])

        c._route.advance(1.5)                       # now inside the arrival window
        read((6, '0010'))
        e = c.snapshot()['route_display']['last_encounter']
        check('the correct later tag is accepted inside the window',
              e['action'] == 'station accepted' and e['station'] == '3')
        check('accepted arrival advances the displayed stage',
              c.snapshot()['route']['station'] == '3'
              and c.snapshot()['route_display']['next_departure_direction'] == 'inbound')


TESTS = [test_display_metadata, test_batched_and_rejected_outcomes]
