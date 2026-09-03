"""The web tier: the watchdog opt-in and the read-only monitor page."""
import math
import re
import os
import pathlib
import struct
import sys
import threading

from helpers import FAIL, ROOT, check

import autopilot
import config
import kinematics
import motion

def test_monitor_page_does_not_feed_the_watchdog():
    """A read-only page must not hold an auto run alive.

    /api/state used to call keepalive() unconditionally, so ANY page polling it
    fed the auto watchdog - meaning a monitoring page open on a second screen
    would keep a run going after the auto page had been closed. The heartbeat is
    now opt-in, and forgetting the flag stops the run rather than extending it.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe monitoring page cannot hold a run alive")

    seen = []
    real = webapp.ctl.keepalive
    webapp.ctl.keepalive = lambda: seen.append(1)
    try:
        c = webapp.app.test_client()
        c.get("/api/state")
        check("/api/state alone does NOT refresh the watchdog", not seen,
              f"{len(seen)} refresh(es)")
        c.get("/api/can")
        check("/api/can does NOT refresh the watchdog", not seen)
        c.get("/api/state?hb=1")
        check("/api/state?hb=1 DOES refresh the watchdog", len(seen) == 1)
    finally:
        webapp.ctl.keepalive = real

    # Only the page that drives the vehicle may claim it.
    auto = (ROOT / "app" / "templates" / "auto.html").read_text()
    mon = (ROOT / "app" / "templates" / "monitor.html").read_text()
    common = (ROOT / "app" / "static" / "common.js").read_text()
    check("the auto page claims the heartbeat", "CLAIM_HEARTBEAT = true" in auto)
    check("the monitor page does not", "CLAIM_HEARTBEAT" not in mon)
    check("the claim is declared before common.js polls",
          "prescript" in auto and "prescript" in
          (ROOT / "app" / "templates" / "base.html").read_text())
    check("common.js only sends hb=1 when the page claims it",
          "CLAIM_HEARTBEAT ? '/api/state?hb=1'" in common)

    # The page itself must render and be read-only.
    c = webapp.app.test_client()
    body = c.get("/monitor").get_data(as_text=True)
    check("the monitor page renders", "Diagnostic only" in body)
    check("it states the golden rule", "not a safety path" in body)
    check("it publishes the write deny-list", "403Eh" in body and "40D0h" in body)
    check("it has no controls", "<button" not in body)



def test_web_cannot_start_the_vehicle():
    """The web app may produce motion by exactly one route: the manual arrows.

    Arming and starting an auto run belong to the physical panel, so the routes
    that did those are GONE rather than guarded - a stale browser tab gets a 404
    instead of a moving vehicle.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe web app cannot start the vehicle")
    c = webapp.app.test_client()

    for route in ("/api/arm", "/api/auto/run"):
        check(f"POST {route} is gone", c.post(route, json={}).status_code == 404,
              str(c.post(route, json={}).status_code))

    # What survives only ever stops, or is a dead-man the operator must hold.
    for route in ("/api/disarm", "/api/stop", "/api/drive"):
        check(f"POST {route} still resolves",
              c.post(route, json={"dir": "stop"}).status_code != 404)

    src = (ROOT / "app" / "server.py").read_text()
    check("no arm route is defined at all", '"/api/arm"' not in src)
    check("no auto-run route is defined at all", '"/api/auto/run"' not in src)

    # The auto page is display-only, so it must offer nothing to press.
    auto = c.get("/auto").data.decode()
    check("the auto page has no controls", "<button" not in auto)
    check("...and says where they went", "from the panel" in auto)

    # The manual page keeps DISARM - removing a stop path is the wrong
    # direction - but must not offer ARM.
    man = c.get("/manual").data.decode()
    check("the manual page keeps DISARM", 'id="disarm"' in man)
    check("...but cannot arm", 'id="arm"' not in man)
    check("...and says arming happens at the panel", "Arm at the panel" in man)

    # A dangling handler for a deleted button is a ReferenceError that kills the
    # whole onState callback and silently freezes the page's telemetry.
    js = (ROOT / "app" / "static" / "auto.js").read_text()
    for dead in ("runBtn", "armBtn", "/api/arm", "/api/auto/run"):
        check(f"auto.js has no reference to {dead}", dead not in js)


def test_lidar_page_is_read_only_and_never_reads_clear():
    """The lidar page shows a non-safety data source, and must look like it."""
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe lidar page is read-only and fails loud")
    c = webapp.app.test_client()

    body = c.get("/lidar").get_data(as_text=True)
    check("the lidar page renders", "Cut-off paths" in body)
    check("it says it is not a safety path", "Not a safety path" in body)
    check("it names the OSSD chain rather than implying this one stops",
          "OSSD" in body and "FX3" in body)
    # There IS a button now - the scan toggle - so the assertion has to be
    # about what a control can DO, not whether one exists. The page has no POST
    # endpoint to call and no handler that calls one.
    ids = re.findall(r'<button[^>]*id="([^"]+)"', body)
    check("the only control is the scan toggle", ids == ["scan-toggle"], str(ids))
    check("...and it moves nothing", "api(" not in
          (ROOT / "app" / "static" / "lidar.js").read_text())
    # sec 5: the protective field ends at 2.15 m, not the 3 m on the datasheet
    # headline, and planner behaviour designed around 3 m would be wrong.
    check("it publishes the real protective range", "2.15" in body)

    # The cloud is a separate GET, for the same reason /api/can is: a picture
    # polled several times a second must not touch the auto watchdog.
    seen = []
    real = webapp.ctl.keepalive
    webapp.ctl.keepalive = lambda: seen.append(1)
    try:
        check("/api/lidar resolves", c.get("/api/lidar").status_code == 200)
        check("/api/lidar does NOT refresh the watchdog", not seen)
    finally:
        webapp.ctl.keepalive = real
    check("there is no POST counterpart",
          c.post("/api/lidar", json={}).status_code == 405)
    check("the lidar page does not claim the heartbeat",
          "CLAIM_HEARTBEAT" not in body)

    # The rule the page exists to enforce. Dimming is what io.js does for the
    # DIO grid; here a dim lamp would still read as "path clear", so staleness
    # has to LIGHT the lamps instead.
    # The rule now lives in common.js's zoneState, shared with the rail every
    # page shows - so it is asserted there, once, where it is defined.
    js = (ROOT / "app" / "static" / "common.js").read_text()
    zs = js[js.index("function zoneState"):js.index("function renderRail")]
    check("staleness lights the zone lamps rather than dimming them",
          "z.stale)   return {on: true" in zs)
    check("...and stale is tested before validity and before the paths",
          zs.index("z.stale") < zs.index("z.validated") < zs.index("paths[i])"))
    check("an unreadable path is not rendered as clear",
          "UNREAD" in zs and "paths[i] === null" in zs)
    check("clear is the ONLY branch that leaves the lamp off",
          zs.count("on: false") == 1, str(zs.count("on: false")))
    check("the page states the bearing convention is unverified",
          "not yet verified" in body)


def test_manual_page_shows_the_rfid_tag():
    """Reading a tag's value means jogging over it, which happens on /manual."""
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe manual page shows the station tag")
    c = webapp.app.test_client()

    man = c.get("/manual").get_data(as_text=True)
    for el in ('id="r-tag"', 'id="r-age"', 'id="r-count"', 'id="r-link"'):
        check(f"/manual carries {el}", el in man)
    check("...and says what it is", "Station tags" in man)

    # One definition, not two. A copy in both files is a copy that gets fixed
    # in one of them - which is the whole reason renderSensor lives in
    # common.js rather than being duplicated per page.
    common = (ROOT / "app" / "static" / "common.js").read_text()
    auto = (ROOT / "app" / "static" / "auto.js").read_text()
    check("showRfid is defined in common.js", "function showRfid" in common)
    check("...and not in auto.js", "function showRfid" not in auto)
    check("common.js calls it from the shared poll", "showRfid(s.rfid" in common)

    # Removing the handler from auto.js must not have left a dangling reference:
    # that is a ReferenceError inside onState, which silently freezes the whole
    # page's telemetry. Same failure that the arm/run removal nearly shipped.
    for dead in ("runBtn", "armBtn", "/api/arm", "/api/auto/run", "r-branch"):
        check(f"auto.js has no reference to {dead}", dead not in auto)

    # Adding a section must not have turned /manual into a watchdog claimant.
    check("/manual still does not claim the heartbeat",
          "CLAIM_HEARTBEAT" not in man)
    check("/manual still cannot arm", 'id="arm"' not in man)
    check("/manual still keeps DISARM", 'id="disarm"' in man)


def test_the_shared_rail_is_on_every_page():
    """Battery, state, alarm and the lidar zones travel with every page.

    And the three diagnostics that used to sit there do NOT: loop timing,
    frames-per-tick and the watchdog countdown are for somebody tuning the
    control loop, and they were taking four of the six rail slots on a screen an
    operator reads at arm's length.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe shared rail carries what an operator needs")
    c = webapp.app.test_client()

    OPERATOR = ('id="batt"', 'id="vstate"', 'id="alarm"', 'id="zone-rail"')
    DIAGNOSTIC = ('id="loop-work"', 'id="loop-frames"', 'id="wd"')

    for page in ("/manual", "/auto", "/io", "/lidar", "/alarms", "/params"):
        body = c.get(page).get_data(as_text=True)
        for el in OPERATOR:
            check(f"{page} carries {el}", el in body)
        for el in DIAGNOSTIC:
            check(f"{page} does NOT carry {el}", el not in body)

    mon = c.get("/monitor").get_data(as_text=True)
    for el in OPERATOR + DIAGNOSTIC:
        check(f"/monitor carries {el}", el in mon)

    # The tiles moved, so every write to them has to be guarded. An unguarded
    # getElementById(...).textContent for a tile that is not on this page throws
    # inside poll() and silently freezes ALL of the page's telemetry.
    common = (ROOT / "app" / "static" / "common.js").read_text()
    check("common.js writes the watchdog through a guarded setter",
          "setText('wd'" in common
          and "document.getElementById('wd').textContent" not in common)
    check("...and the setpoint too", "setText('setpoint'" in common)
    check("renderLoopHealth returns early when its tiles are absent",
          "if (!work || !lp) return;" in common)

    # The verdicts are computed once, on the server. Four pages each deciding
    # what "alarm" means is four chances for one of them to say all is well.
    worker = (ROOT / "canworker.py").read_text()
    check("the alarm verdict is computed server-side", "def _alarm(" in worker)
    check("the battery summary is computed server-side", "def _battery(" in worker)
    check("both reach the browser through the state snapshot",
          '"alarm": self._alarm(' in worker and '"battery": _battery(' in worker)


def test_the_scan_is_off_until_asked_for():
    """The picture costs CPU, so it is drawn only while somebody is looking."""
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe lidar scan is off by default")
    c = webapp.app.test_client()

    body = c.get("/lidar").get_data(as_text=True)
    check("the toggle starts in the off state", ">Start scan<" in body)
    check("...and says so", "off by default" in body)

    js = (ROOT / "app" / "static" / "lidar.js").read_text()
    check("scanOn starts false", "let scanOn = false;" in js)
    check("the page initialises through setScan(false), not a bare poll",
          "setScan(false);" in js and "\npollCloud();" not in js)
    check("a poll while off makes NO request at all",
          "if (!scanOn) return;" in js)
    # Leaving the page stops it for free - the script is destroyed - but a tab
    # left in the background is still "not looking".
    check("hiding the tab stops the scan",
          "visibilitychange" in js and "document.hidden" in js)
    # Turning it off must not leave the last picture on screen looking live.
    check("toggling clears the held cloud", "cloud = null;" in
          js[js.index("function setScan"):js.index("function setScan") + 400])
    check("an off scan says so rather than reading as an empty room",
          "'scan off'" in js)

    # The lamps must NOT depend on the toggle: they ride on the state poll.
    check("the zone lamps are painted from /api/state, not from the cloud",
          "paintZones(l.zones)" in js)


def test_alarms_page_records_but_cannot_clear():
    """Colour-coded log plus what is standing. It must not be able to silence."""
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe alarms page records and cannot clear")
    c = webapp.app.test_client()

    body = c.get("/alarms").get_data(as_text=True)
    check("the alarms page renders", "Standing" in body and "Log" in body)
    check("it is reachable from every page",
          'href="/alarms"' in c.get("/manual").get_data(as_text=True))
    check("it says a fault is cleared at the panel", "panel" in body
          and "Reset" in body)

    # The one thing this page must never do. An acknowledge button on a browser
    # silences an alarm for somebody standing somewhere else.
    js = (ROOT / "app" / "static" / "alarms.js").read_text()
    check("there is no acknowledge or clear control",
          "<button" not in body)
    check("...and no POST from the page", "api(" not in js)
    check("events.clear is not reachable from the web",
          "clear" not in (ROOT / "app" / "server.py").read_text().split("def api_events")[1][:400])

    # Three levels, three colours, and the level is never carried by colour
    # alone - a colour-only scheme vanishes in a photograph of the screen,
    # which is how a fault usually reaches somebody who was not there.
    css = (ROOT / "app" / "static" / "app.css").read_text()
    for cls in ("lv-info", "lv-warn", "lv-error"):
        check(f"{cls} is styled", f".{cls}" in css)
    check("the level is also printed as text", 'class="al-lv"' in js)
    check("colour is carried by a left bar, not a fill alone",
          "border-left-color:var(--stop)" in css
          and "border-left-color:var(--hazard)" in css)

    # Errors cannot be filtered away.
    check("info and warn are filterable", 'id="f-info"' in body and 'id="f-warn"' in body)
    check("errors are not", "disabled" in body and "always shown" in body)
    check("the filter always keeps errors", "e.level === 'error'" in js)

    # Event text is operator-visible and can contain anything an exception's
    # str() produced, so it must never be interpolated into HTML.
    check("event text is set through textContent, not innerHTML",
          ".textContent = shown[i].msg" in js)


def test_params_page_displays_and_cannot_edit():
    """The parameters page shows the whole tuning surface and can change none
    of it.

    Two failures it is built against. The first is the ordinary one: a value
    that can be edited from a browser is a value that can be edited while
    somebody is standing next to the vehicle, so there is no write endpoint to
    guard - there is no write endpoint at all. The second is quieter and is why
    the page is GENERATED from config's schema: a hand-written parameters page
    stops matching the profile the moment a key is added, and what it then
    shows is a value the vehicle is not running on.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe parameters page displays and cannot edit")
    c = webapp.app.test_client()

    body = c.get("/params").get_data(as_text=True)
    check("the params page renders", "Display only" in body)
    check("it names the profile and the file it came from",
          config.PROFILE_NAME in body and config.PROFILE_PATH_LOADED in body)
    check("...and says how a parameter IS changed",
          "restarting the service" in body)
    check("it is reachable from every page",
          'href="/params"' in c.get("/manual").get_data(as_text=True))

    # Nothing to press, nothing to POST, and no route that writes a profile.
    check("there are no controls", "<button" not in body)
    js = (ROOT / "app" / "static" / "params.js").read_text()
    check("the page makes no POST", "api(" not in js)
    check("...and no request of any kind", "fetch(" not in js
          and "apiGet(" not in js)
    src = (ROOT / "app" / "server.py").read_text()
    check("there is no endpoint that writes a profile",
          "/api/params" not in src and "config.load(" not in src)
    check("the params page does not claim the heartbeat",
          "CLAIM_HEARTBEAT" not in body)

    # The whole profile reaches the screen. Generated, so this cannot pass by
    # somebody having remembered to add a row.
    absent = [f"{sec}.{key}" for sec, fields in config._SCHEMA.items()
              for key, (const, _t) in fields.items() if const not in body]
    check("every parameter in the schema reaches the page", not absent,
          str(absent))
    check("derived values are shown apart, as underivable from the JSON",
          "derived" in body and "MPS_PER_RPM" in body
          and "cannot be edited" in body)

    # The prose is config.py's, parsed out of it. If it were copied into the
    # template there would be two of every explanation and one would rot.
    note = "tape to the RIGHT of the sensor"
    tpl = (ROOT / "app" / "templates" / "params.html").read_text()
    check("a tuning note reaches the page", note in body)
    check("...from config.py, not from the template",
          note in (ROOT / "config.py").read_text() and note not in tpl)


TESTS = [
    test_params_page_displays_and_cannot_edit,
    test_web_cannot_start_the_vehicle,
    test_monitor_page_does_not_feed_the_watchdog,
    test_lidar_page_is_read_only_and_never_reads_clear,
    test_manual_page_shows_the_rfid_tag,
    test_the_shared_rail_is_on_every_page,
    test_the_scan_is_off_until_asked_for,
    test_alarms_page_records_but_cannot_clear,
]
