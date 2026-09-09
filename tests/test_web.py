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

    # The page itself must render and be read-only. The "diagnostic only, not a
    # safety path" banner that used to head it was removed by request, so what
    # is asserted here is the PROPERTY rather than the prose: no controls, no
    # way to write, and the deny-list on screen.
    c = webapp.app.test_client()
    body = c.get("/monitor").get_data(as_text=True)
    check("the monitor page renders",
          'id="mon-state"' in body and "Control loop" in body)
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

    # /api/restart belongs in that group - it de-energises and ends the process,
    # so the worst it can do is stop the vehicle - but it is checked through the
    # URL map rather than by calling it. On a machine where the unit exists and
    # nothing is armed, both guards pass and the handler does exactly what it
    # says: os._exit(1), taking this test run with it.
    rules = {r.rule: r.methods for r in webapp.app.url_map.iter_rules()}
    check("POST /api/restart is registered", "POST" in rules.get("/api/restart", set()))
    check("...and is POST-only, so a link cannot trigger it",
          "GET" not in rules.get("/api/restart", set()))

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
    # The "not a safety path" and "cut-off paths are unvalidated" banners were
    # removed from this page by request. Neither was doing the work: the rule
    # they described is enforced in zoneState() below, which is asserted here
    # and is what actually keeps an unknown or dead stream off "clear".
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
    # Said on the standing-fault row itself rather than in a banner at the top -
    # the banner was removed by request, and the row is where somebody reading
    # about a live fault is actually looking.
    check("a latched fault says it is cleared at the panel",
          "clear with panel Reset"
          in (ROOT / "app" / "static" / "alarms.js").read_text())

    # The one thing this page must never do. An acknowledge button on a browser
    # silences an alarm for somebody standing somewhere else.
    #
    # This used to be asserted as "no <button> anywhere on the page", which was
    # broader than the rule it was protecting - the page now carries a service
    # restart, which is the opposite of silencing: it de-energises the drives
    # and throws the log away rather than tidying it. So the checks name the
    # forbidden thing instead of forbidding all controls.
    js = (ROOT / "app" / "static" / "alarms.js").read_text()
    srv = (ROOT / "app" / "server.py").read_text()
    for banned in ("id=\"ack\"", "id=\"clear\"", "acknowledge", "Acknowledge"):
        check(f"no {banned} control on the page", banned not in body)
    check("the only endpoint the page POSTs to is the restart",
          [c for c in re.findall(r"api\('([^']+)'", js)] == ["/api/restart"],
          str(re.findall(r"api\('([^']+)'", js)))
    check("there is no endpoint that clears a fault or an alarm",
          "/api/clear" not in srv and "/api/ack" not in srv)
    check("events.clear is not reachable from the web",
          "clear" not in srv.split("def api_events")[1][:400])
    # The restart is a stop, so it must be refused while the vehicle is armed -
    # a control that de-energises on a whim is the hazard, not the button.
    check("the restart is refused while armed",
          'snap.get("armed")' in srv and "disarm before restarting" in srv)
    check("...and refuses when nothing would restart the process",
          '("on-failure", "always")' in srv)
    check("the page says it de-energises the drives",
          "de-energises the drives" in body)

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
    # The "display only" banner was removed by request. Read-onlyness is a fact
    # about the endpoints, not about a paragraph, and it is asserted as such a
    # few lines down - there is nothing to press and nothing to POST to.
    check("the params page renders", "Profile" in body and "pm-list" in body)
    check("it names the profile and the file it came from",
          config.PROFILE_NAME in body and config.PROFILE_PATH_LOADED in body)
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


def test_params_page_reads_speed_first():
    """Speed is the most-consulted and most-edited part of the profile, and it
    was spread across three sections. It is gathered into one at the top.

    The invariant that matters is not the order - it is that gathering a row
    MOVES it rather than copying it. A parameter printed in two places is a
    parameter that can be read as two parameters, and the one somebody edits
    will be the one the vehicle is not using.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe parameters page reads speed first")
    c = webapp.app.test_client()

    secs = config.describe()
    names = [s["name"] for s in secs]
    # The synthetic blocks lead; the schema's own sections follow in the order
    # _SECTION_ORDER names. Asserted separately so adding another synthetic
    # block does not look like the schema order breaking.
    check("the gathered blocks lead", names[0] == "speed", str(names[:3]))
    schema_order = [n for n in names if n in config._SCHEMA]
    check("then the control law, then the geometry",
          schema_order[:2] == ["autopilot", "vehicle"], str(schema_order[:3]))

    speed = next(s for s in secs if s["name"] == "speed")
    keys = [r["key"] for r in speed["rows"]]
    check("both manual jog speeds are there",
          "manual.full_rpm" in keys and "manual.half_ratio" in keys
          and "manual.spin_ratio" in keys, str(keys))
    check("both auto speeds are there, slow included",
          "autopilot.auto_rpm" in keys and "autopilot.auto_slow_rpm" in keys)
    check("and the driver ramps that shape them",
          len([k for k in keys if k.startswith("drivers.ramp.")]) == 4)
    check("every gathered row names the section it lives in, so it can be found "
          "in the JSON", all("." in k for k in keys), str(keys))

    # The real guard. Not order - duplication.
    consts = [r["const"] for s in secs for r in s["rows"] if r["const"]]
    dupes = sorted({c for c in consts if consts.count(c) > 1})
    check("no parameter is printed twice", not dupes, str(dupes))

    # And the mirror of it: nothing may be lost on the way. Suppressing a row
    # from its home section and forgetting to gather it would be silent.
    shown = set(consts)
    missing = [f"{sec}.{key}" for sec, fields in config._SCHEMA.items()
               for key, (const, _t) in fields.items() if const not in shown]
    check("...and none is lost by being moved", not missing, str(missing))

    # A section emptied by the gathering must not leave a bare heading behind.
    check("an emptied section is dropped, not shown blank",
          all(s["rows"] for s in secs) and "manual" not in names, str(names))

    body = c.get("/params").get_data(as_text=True)
    check("the page renders the gathered section first",
          body.index("speed") < body.index("autopilot"))
    check("...and says where those keys actually live",
          "autopilot.auto_slow_rpm" in body)


def test_params_lists_the_rfid_rules():
    """Every kind of thing a station tag can mean, grouped by function, with the
    free slots shown rather than omitted.

    A page listing only the two implemented rules looks complete, and the next
    person needs to see there is room for more before inventing a ninth
    mechanism somewhere else.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe parameters page lists the RFID rules")
    c = webapp.app.test_client()

    secs = config.describe()
    names = [s["name"] for s in secs]
    check("the block sits directly after speed",
          names[:2] == ["speed", "rfid rules"], str(names[:3]))

    rules = next(s for s in secs if s["name"] == "rfid rules")
    keys = [r["key"] for r in rules["rows"]]
    heads = [k for k in keys if "\u00b7" in k]
    check(f"there are {config.RFID_RULE_SLOTS} rule types",
          len(heads) == config.RFID_RULE_SLOTS, str(heads))
    check("the implemented ones are named first",
          "branch latch" in heads[0] and "stop until start button" in heads[1],
          str(heads[:2]))
    check("the rest are numbered free slots",
          all("undefined rule" in h for h in heads[3:]), str(heads[3:]))

    # Loaded rules appear under their own type, not in a flat list.
    for r in config.BRANCH_LATCH:
        check(f"junction {r['entry_tag']} is listed",
              any(r["entry_tag"] in k for k in keys), str(keys))
    for direction, tag in config.STOP_TAGS:
        check(f"station tag {tag} is listed",
              any(tag in k for k in keys), str(keys))

    # With no junction tags loaded, the branch-latch slot reads "none loaded" -
    # which on its own says the vehicle carries straight on, and it no longer
    # does. The standing default has to appear in the block that answers "what
    # happens at a junction", not only in the autopilot section.
    if config.BRANCH_DEFAULT != "straight":
        side = "rightmost" if config.BRANCH_DEFAULT == "right" else "leftmost"
        check("the standing branch default is listed with the junction rules",
              any(f"take the {side} tape" in str(r.get("value"))
                  for r in rules["rows"]), str(keys))
        check("...and is on the page, not just in the model",
              f"take the {side} tape" in c.get("/params").get_data(as_text=True))

    # The old standalone branch_latch section is gone, not duplicated - the
    # no-duplicates invariant in test_params_page_reads_speed_first would catch
    # it, but say so here too since removing it was the point.
    check("the junction table is not also listed on its own",
          "branch_latch" not in names, str(names))

    body = c.get("/params").get_data(as_text=True)
    check("it renders", "rfid rules" in body and "undefined rule 5" in body)
    check("...and explains direction-qualified rules",
          "direction-qualified" in body)
    check("...and counts the tags in use",
          f"{len({t for r in config.BRANCH_LATCH for t in (r['entry_tag'], r['exit_tag'])} | {t for dr, t in config.STOP_TAGS} | {t for r in config.HIGH_SPEED_MODE for t in (r['entry_tag'], r['exit_tag'])})} tag id(s)"
          in body)


def test_landing_page_is_auto_and_the_pill_says_armed():
    """The bare address lands on /auto, and the header pill answers "is this
    vehicle energised?" rather than naming the CAN adapter.

    The pill is the only always-visible indicator on seven pages, so the two
    failure states have to outrank the armed state in it. "DISARMED" is a
    reassuring word, and showing it while the bus is missing would be a lie of
    exactly the kind this codebase keeps out of the rail.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe landing page is /auto and the pill says armed")
    c = webapp.app.test_client()

    r = c.get("/")
    check("the bare address redirects", r.status_code in (301, 302),
          str(r.status_code))
    check("...to /auto", r.headers.get("Location", "").endswith("/auto"),
          r.headers.get("Location"))

    common = (ROOT / "app" / "static" / "common.js").read_text()
    check("the pill shows armed state", "'ARMED' : 'DISARMED'" in common)
    check("a silent driver still outranks it",
          "DRIVER SILENT" in common
          and common.index("DRIVER SILENT") < common.index("'ARMED' : 'DISARMED'"))
    check("...and so does a missing bus",
          "!s.connected" in common
          and common.index("!s.connected") < common.index("'ARMED' : 'DISARMED'"))
    check("the bus identity is no longer in the pill",
          "s.how + (s.armed" not in common)

    # It moved rather than being deleted: which adapter can0 resolved to is a
    # fault-finding fact, and /monitor is the fault-finding page.
    mon = c.get("/monitor").get_data(as_text=True)
    check("/monitor carries the bus identity instead", 'id="bus-how"' in mon)
    check("...fed from /api/can, which does not claim the watchdog",
          "renderBus" in (ROOT / "app" / "static" / "monitor.js").read_text())
    for page in ("/manual", "/auto", "/io", "/lidar", "/alarms", "/params"):
        check(f"{page} does not carry the bus tile",
              'id="bus-how"' not in c.get(page).get_data(as_text=True))


def test_wifi_indicator_reports_but_never_acts():
    """Bars and dBm in the header. It must stay a readout and nothing else.

    The temptation with a link-quality number is to make something depend on
    it - refuse to arm below two bars, stop on a drop. That would be a second,
    softer watchdog competing with the real one: MANUAL_WATCHDOG_S already
    zeroes the setpoint when the browser stops re-POSTing, and it does so for
    a flat battery and a closed tab as well as a weak link. This only explains
    what is about to happen.
    """
    import server as webapp   # app/server.py; see the note on the rename
    import wifi
    print("\nthe wifi indicator reports and does not act")

    # -- the mapping -------------------------------------------------------
    check("a strong link is four bars", wifi.bars_for(-40) == 4)
    check("the -67 dBm voice/video floor is inside two bars",
          wifi.bars_for(-67) == 2)
    check("a marginal link is one bar", wifi.bars_for(-78) == 1)
    check("below -80 dBm is none", wifi.bars_for(-85) == 0)
    check("not associated is none", wifi.bars_for(None) == 0)
    prev = [wifi.bars_for(d) for d in range(-30, -95, -5)]
    check("bars never rise as the signal falls",
          all(a >= b for a, b in zip(prev, prev[1:])), str(prev))

    # -- parsing -----------------------------------------------------------
    HEAD = ("Inter-| sta-|   Quality        |   Discarded packets\n"
            " face | tus | link level noise |  nwid  crypt   frag\n")
    rows = wifi._parse(HEAD + "wlp1s0: 0000   70.  -39.  -256   0  0  0\n")
    check("a normal row parses", rows and rows[0]["dbm"] == -39.0
          and rows[0]["iface"] == "wlp1s0", str(rows))
    check("the trailing dot is not read as a decimal point",
          rows[0]["quality"] == 70.0)

    # An idle card reports level 0. Four bars for that is the one genuinely
    # misleading thing this module could draw.
    idle = wifi._parse(HEAD + "wlan9: 0000    0.    0.  -256   0  0  0\n")
    check("an unassociated interface reports no dBm rather than 0",
          idle and idle[0]["dbm"] is None, str(idle))
    check("...and therefore no bars", wifi.bars_for(idle[0]["dbm"]) == 0)
    check("a truncated line is skipped, not raised on",
          wifi._parse(HEAD + "broken:\n") == [])

    # -- absent radio ------------------------------------------------------
    real, wifi.PROC = wifi.PROC, str(ROOT / "does-not-exist")
    wifi.reset()
    try:
        gone = wifi.snapshot()
    finally:
        wifi.PROC = real
        wifi.reset()
    check("a machine with no radio reports present=False",
          gone["present"] is False)
    check("...so the indicator hides rather than showing zero bars",
          gone["bars"] == 0 and gone["dbm"] is None)

    # -- the endpoint ------------------------------------------------------
    c = webapp.app.test_client()
    body = c.get("/api/state").get_json()
    check("/api/state carries the wifi block", "wifi" in body)
    for key in ("present", "bars", "dbm", "weak"):
        check(f"...with {key}", key in body["wifi"])

    # Reading the header must not have turned the state poll into a heartbeat.
    seen = []
    realka, webapp.ctl.keepalive = webapp.ctl.keepalive, lambda: seen.append(1)
    try:
        c.get("/api/state")
        check("the wifi merge did not make /api/state feed the watchdog",
              not seen)
    finally:
        webapp.ctl.keepalive = realka

    # -- it is a readout --------------------------------------------------
    # Not a health source: health.py's table is what stops modes, and a link
    # to the OPERATOR does not belong in a table about devices on the vehicle.
    worker = (ROOT / "canworker.py").read_text()
    check("the bus thread knows nothing about wifi", "wifi" not in worker)
    src = (ROOT / "core" / "wifi.py").read_text()
    # Imports, not prose: the docstring explains why netlink and a subprocess
    # were rejected, so a bare substring search finds the words that forbid it.
    check("the module opens nothing but /proc",
          "import subprocess" not in src and "import socket" not in src)
    check("...and cannot write anywhere", "open(" in src
          and '"w"' not in src and "'w'" not in src)

    # It rides on the poll every page already makes, so it must be guarded the
    # way every other shared-rail tile is - an unguarded write for an element
    # a page lacks throws inside poll() and freezes ALL telemetry.
    common = (ROOT / "app" / "static" / "common.js").read_text()
    check("renderWifi returns early when the header element is absent",
          "if (!box) return;" in common)
    check("...and is called from the shared poll", "renderWifi(s.wifi)" in common)

    # On every page, since the header is in base.html.
    for page in ("/manual", "/auto", "/io", "/lidar", "/alarms", "/monitor"):
        page_body = c.get(page).get_data(as_text=True)
        check(f"{page} carries the indicator", 'id="wifi-bars"' in page_body)
        check(f"{page} starts it hidden", 'id="wifi"' in page_body
              and "hidden" in page_body)


def test_outputs_are_not_commandable_from_a_browser():
    """dio now WRITES a coil. That must not become a button.

    The horn is the first output this software energises, and the risk of a
    write path is not the write - it is that the next person adds an endpoint
    to exercise it, one click away from a coil on a vehicle somebody is
    standing next to. The DIO driver's own docstring named that hazard before
    there was any write phase at all; this is the check that keeps it named.
    """
    import server as webapp
    print("\nthe I/O page cannot command an output")
    c = webapp.app.test_client()

    src = (ROOT / "app" / "server.py").read_text()
    check("no coil route is defined", "set_coil" not in src)
    check("no output route is defined", '"/api/do' not in src and
          '"/api/io' not in src)

    for route in ("/api/do", "/api/coil", "/api/horn", "/api/output"):
        check(f"POST {route} is not a route",
              c.post(route, json={}).status_code == 404)

    js = (ROOT / "app" / "static" / "io.js").read_text()
    check("io.js posts nothing", "fetch(" not in js and "post" not in js.lower())
    check("...and binds no handler", "addEventListener" not in js
          and "onclick" not in js)

    html = c.get("/io").data.decode()
    check("the I/O page has no controls", "<button" not in html)
    check("...and says who does command the outputs",
          "commanded by the vehicle" in html)

    # The page must be able to tell a coil being HELD low from one nothing is
    # driving. On an output those look identical and mean opposite things.
    check("the page renders which coils are claimed", "do-c-" in html)
    check("io.js reads the claim out of the snapshot", "commanded" in js)


def test_the_horn_is_reported_but_gates_nothing():
    """A horn is a warning, not an interlock. Nothing may depend on it."""
    import server as webapp
    print("\nthe horn warns and nothing waits for it")

    check("the horn is on a real coil",
          0 <= config.HORN_DO_CHANNEL < config.DIO_NUM_DO)
    check("...and that channel is labelled on the /io page - an unnamed lamp "
          "beside a device that makes noise is a trap",
          config.DIO_DO_NAMES[config.HORN_DO_CHANNEL] != "",
          config.DIO_DO_NAMES[config.HORN_DO_CHANNEL])

    # The vehicle must still move with the horn broken, disabled, or on a dead
    # module. If anything ever reads HORN_* to decide whether to drive, a blown
    # bulb becomes a stranded AGV.
    worker = (ROOT / "canworker.py").read_text()
    body = worker[worker.index("def _update_horn"):]
    body = body[:body.index("def _write_target")]
    elsewhere = worker.replace(body, "")
    check("the horn is written in one place and never read back into a "
          "decision", "HORN_" not in elsewhere,
          "HORN_ appears outside _update_horn" if "HORN_" in elsewhere
          else "only _update_horn touches it")

    def method(name):
        """The source of one method, up to the next def at the same indent."""
        seg = worker[worker.index(f"    def {name}("):]
        nxt = re.search(r"\n    (?:def |# ---)", seg[10:])
        return seg[:10 + nxt.start()] if nxt else seg

    for name in ("_do_arm", "drive", "_do_auto_run", "_do_disarm"):
        check(f"{name}() does not consult the horn",
              "horn" not in method(name).lower())

    # It is also not a health source: a horn that stopped answering must not
    # stop the vehicle, for the same reason.
    check("the horn is not registered with health",
          'health.PullSource("horn"' not in worker
          and 'HealthSource("horn"' not in worker)

    st = webapp.app.test_client().get("/api/state")
    if st.status_code == 200:
        dio = (st.get_json() or {}).get("dio") or {}
        check("the snapshot carries the claimed coils for the page",
              "commanded" in dio, str(sorted(dio))[:80])


def test_setpoint_shows_body_speed_and_the_station_window():
    """Two readouts added for the operator: how fast the vehicle is being told
    to go, and why a station just went past without stopping it.

    Both are DERIVED displays of numbers already on the page, which is the risk
    worth testing: a derived number that is computed in the browser from a
    constant typed into JS goes on looking plausible after the profile changes.
    """
    import server as webapp   # app/server.py; see the note on the rename
    print("\nthe setpoint tile shows m/s, and the station window is visible")

    c = webapp.app.test_client()
    common = (ROOT / "app" / "static" / "common.js").read_text()
    autojs = (ROOT / "app" / "static" / "auto.js").read_text()

    # -- the conversion is served, not hardcoded ---------------------------
    st = c.get("/api/state").get_json()
    check("the state carries the r/min -> m/s conversion",
          st.get("mps_per_rpm") == config.MPS_PER_RPM, str(st.get("mps_per_rpm")))
    check("...and it is the SAME constant the vehicle runs on, not a literal "
          "typed into JS",
          "mps_per_rpm" in common
          and not re.search(r"0\.000?31", common), "a hardcoded ratio would go "
          "stale the moment wheel_dia_m or gear_ratio changed")

    # -- the arithmetic ----------------------------------------------------
    # For a differential drive the body's forward speed IS the mean of the two
    # wheel speeds, so "average them on a corner" is exact rather than an
    # approximation. Checked here in Python against the same constant the
    # browser is handed.
    def mps(l, r):
        return (l + r) / 2 * config.MPS_PER_RPM

    straight = mps(config.AUTO_RPM, config.AUTO_RPM)
    check("straight ahead converts the commanded r/min",
          abs(straight - config.AUTO_RPM * config.MPS_PER_RPM) < 1e-9,
          f"{straight:.2f} m/s")
    corner = mps(config.MANUAL_HALF_RPM, config.MANUAL_FULL_RPM)
    check("a corner averages the pair, and lands between the two wheels",
          mps(config.MANUAL_HALF_RPM, config.MANUAL_HALF_RPM) < corner
          < mps(config.MANUAL_FULL_RPM, config.MANUAL_FULL_RPM),
          f"{corner:.2f} m/s")
    check("*** a spin on the spot is 0.00 m/s, not half of full ***",
          abs(mps(-config.MANUAL_FULL_RPM, config.MANUAL_FULL_RPM)) < 1e-9,
          "the vehicle turns but does not travel, and the mean says so")
    check("a stopped vehicle reads zero", abs(mps(0, 0)) < 1e-9)

    # -- and it is on both pages, because the tile is shared ---------------
    for page in ("/auto", "/manual"):
        body = c.get(page).get_data(as_text=True)
        check(f"{page} carries the setpoint tile's m/s slot",
              'id="setpoint-mps"' in body)
    check("two decimal places, as asked", "toFixed(2)" in common)

    # -- the station window ------------------------------------------------
    check("the state reports the route", "route" in st)
    check("startup reports the initial parked route position",
          st["route"]["parked"], str(st["route"]))

    body = c.get("/auto").get_data(as_text=True)
    check("the auto page has a station tile", 'id="p-stn"' in body)
    check("...and it shows both states", "r.parked" in autojs
          and "travel_direction" in autojs)
    check("...on its own tile, so a PID guard and a station stop cannot "
          "displace each other",
          "p-stn" in autojs and "AT STATION" not in
          autojs[autojs.index("function showHold"):autojs.index("function showStation")])

    # Still a readout. The page has no way to end the window or skip a station.
    check("the station readout gates nothing and posts nothing",
          "/api/" not in autojs, "the auto page is display-only")


TESTS = [
    test_params_page_displays_and_cannot_edit,
    test_params_page_reads_speed_first,
    test_params_lists_the_rfid_rules,
    test_landing_page_is_auto_and_the_pill_says_armed,
    test_web_cannot_start_the_vehicle,
    test_monitor_page_does_not_feed_the_watchdog,
    test_lidar_page_is_read_only_and_never_reads_clear,
    test_manual_page_shows_the_rfid_tag,
    test_the_shared_rail_is_on_every_page,
    test_the_scan_is_off_until_asked_for,
    test_alarms_page_records_but_cannot_clear,
    test_wifi_indicator_reports_but_never_acts,
    test_outputs_are_not_commandable_from_a_browser,
    test_the_horn_is_reported_but_gates_nothing,
    test_setpoint_shows_body_speed_and_the_station_window,
]
