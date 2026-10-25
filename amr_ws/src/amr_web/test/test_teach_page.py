"""Teach page and API (tracked plan 3, P1): engineer-gated teaching, open At home, the site lists."""

from test_operator_ux import app_for


def test_teach_page_and_site_lists(tmp_path):
    client, _stub = app_for({}, tmp_path)
    assert client.get("/teach").status_code == 200
    from agv_core import config
    site = client.get("/api/line/site").get_json()
    # The profile's tape_loc.site_mission: the straight test today, site-103 later.
    assert site["mission"] == config.TAPE_LOC_SITE_MISSION and not site["error"]
    assert config.TAPE_LOC_SHADOW_CIRCUIT in site["circuits"] and site["stations"]


def test_teaching_needs_the_engineer_view(tmp_path):
    client, stub = app_for({}, tmp_path)
    client.post("/api/role", json={"role": "operator"})
    r = client.post("/api/line/teach", json={"action": "pass_start", "arg": "C-MRU"})
    assert r.status_code == 403 and not any(c[0] == "line_teach" for c in stub.calls)
    # At home only sets AMCL's initial pose: open to the operator.
    assert client.post("/api/line/at_home").status_code == 200
    assert ("line_at_home", ()) in stub.calls


def test_the_engineer_teach_call_is_forwarded(tmp_path):
    client, stub = app_for({}, tmp_path)   # engineer is the default view
    r = client.post("/api/line/teach", json={"action": "station", "arg": "MW-1"})
    assert r.status_code == 200 and ("line_teach", ("station", "MW-1")) in stub.calls


def test_the_site_lists_carry_machines_points_and_roles(tmp_path):
    client, _stub = app_for({}, tmp_path)
    site = client.get("/api/line/site").get_json()
    assert site["machines"]["MRU"] == ["MRU1", "MRU2", "MRU3", "MRU4"] and site["trip_calls"] == 2
    assert site["stations"][0] == site["home"] == "HOME-N" and site["live"] is False
    assert site["points"] == ["UT-MRU1", "UT-MRU2", "UT-MRU3"]
    page = client.get("/teach").data
    assert b'id="tc-role"' in page and b'data-act="mark_role"' in page


def test_calls_and_confirmations_are_open_to_the_operator_and_checked(tmp_path):
    client, stub = app_for({}, tmp_path)
    client.post("/api/role", json={"role": "operator"})
    page = client.get("/calls")
    assert page.status_code == 200 and b'data-confirm="confirm_released"' in page.data
    assert b'href="/calls"' in page.data
    r = client.post("/api/line/trip", json={"action": "call", "arg": "MRU2"})
    assert r.status_code == 200 and stub.calls[-1] == ("line_trip", ("call", "MRU2"))
    r = client.post("/api/line/trip", json={"action": "confirm_off", "arg": "ignored"})
    assert r.status_code == 200 and stub.calls[-1] == ("line_trip", ("confirm_off", ""))
    n = len(stub.calls)
    for bad in ({"action": "start"}, {"action": "call", "arg": "MRU 2"}, {"action": "call"}, {}):
        assert client.post("/api/line/trip", json=bad).status_code == 422, bad
    assert len(stub.calls) == n     # nothing refused reached the robot


def test_the_site_mission_is_offered_as_a_job_only_when_live(tmp_path, monkeypatch):
    from agv_core import config
    client, _stub = app_for({}, tmp_path)
    assert config.TAPE_LOC_SITE_MISSION not in client.get("/api/line/missions").get_json()["missions"]
    monkeypatch.setattr(config, "TAPE_LOC_LIVE", True)
    data = client.get("/api/line/missions").get_json()
    assert config.TAPE_LOC_SITE_MISSION in data["missions"] and "Calls page" in data["notes"]["site-103"]


def test_high_speed_areas_are_drawn_by_the_engineer_on_the_teaching_map(tmp_path):
    import json
    import os

    from amr_web import tapegraph_view
    client, _stub = app_for({}, tmp_path)
    sd = client.application.config["STATE_DIR"]
    os.makedirs(sd, exist_ok=True)
    with open(os.path.join(sd, "line_graph.json"), "w") as fh:
        json.dump({"map_id": "m", "map_revision": 2, "graph_revision": None}, fh)
    areas = os.path.join(sd, "teach", "m-rev2", "areas.json")
    assert client.get("/tape-areas").status_code == 200
    sq = [[0, 0], [4, 0], [4, 2], [0, 2]]
    r = client.post("/api/line/areas", json={"id": "H-1", "polygon": sq})
    assert r.status_code == 200 and "H-1 saved on m rev2" in r.get_json()["message"]
    assert json.load(open(areas)) == {"H-1": {"polygon": sq, "kind": "high"}}
    assert tapegraph_view.view(sd, str(tmp_path))["areas"] == [{"id": "H-1", "polygon": sq}]
    sliver = [[0, 0], [0.1, 0], [0, 0.1]]
    for bad in ({"id": "H 2", "polygon": sq}, {"id": "H-2", "polygon": sq[:2]},
                {"id": "H-2", "polygon": sliver}, {"id": "H-2", "polygon": [[0, "a"]] * 3}):
        assert client.post("/api/line/areas", json=bad).status_code == 422, bad
    assert client.post("/api/line/areas", json={"id": "H-1", "delete": True}).status_code == 200
    assert json.load(open(areas)) == {}
    client.post("/api/role", json={"role": "operator"})
    r = client.post("/api/line/areas", json={"id": "H-1", "polygon": sq})
    assert r.status_code == 403
    assert r.get_json()["message"] == "high-speed areas need the engineer view (PIN)"  # D132: verbatim
    # refused before the body is read: a malformed body gets the role answer, not a 400
    assert client.post("/api/line/areas", data="not json", content_type="application/json").status_code == 403
