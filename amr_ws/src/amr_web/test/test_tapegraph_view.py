"""amr_web.tapegraph_view: what the map overlay draws, from the LINE layer's files."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from amr_web import tapegraph_view as tv  # noqa: E402


def _w(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh)


def test_nothing_selected_is_not_available(tmp_path):
    assert tv.view(str(tmp_path), str(tmp_path / "maps"))["available"] is False
    _w(str(tmp_path / "line_graph.json"), {"map_id": "../etc", "map_revision": 1})
    assert tv.view(str(tmp_path), str(tmp_path / "maps"))["available"] is False


def test_before_a_graph_the_newest_pass_and_the_teach_files(tmp_path):
    st, maps = str(tmp_path / "state"), str(tmp_path / "maps")
    _w(f"{st}/line_graph.json", {"map_id": "m", "map_revision": 1, "graph_revision": None})
    teach = f"{st}/teach/m-rev1"
    _w(f"{teach}/passes/C-1.json", {"samples": [[0.0, 0.0, 0.0], [5.0, 5.0, 0.0]]})
    _w(f"{teach}/passes/C-2.json", {"samples": [[i * 0.05, i * 0.05, 0.0] for i in range(101)]})
    _w(f"{teach}/anchors.json", {"J-A": [1.0, 2.0]})
    _w(f"{teach}/marks.json", {"M1": {"pose": [3.0, 0.0, 0.0], "label": "MW-1", "leg": "a", "s": 3.0}})
    _w(f"{teach}/stations.json", {"HOME": {"pose": [0.1, 0.0, 0.0]}})
    v = tv.view(st, maps)
    assert v["available"] and v["legs"] == [] and v["pass"]["name"] == "C-2"
    assert v["pass"]["pts"][0] == [0.0, 0.0] and v["pass"]["pts"][-1] == [5.0, 0.0]
    assert 24 <= len(v["pass"]["pts"]) <= 27             # 5 m thinned to ~0.2 m
    assert v["anchors"] == [{"id": "J-A", "x": 1.0, "y": 2.0}]
    assert v["marks"][0]["label"] == "MW-1" and v["stations"][0]["id"] == "HOME"


def test_an_active_graph_gives_its_legs_and_stations(tmp_path):
    st, maps = str(tmp_path / "state"), str(tmp_path / "maps")
    _w(f"{st}/line_graph.json", {"map_id": "m", "map_revision": 1, "graph_revision": 2})
    _w(f"{maps}/m/tapegraph/g2/graph.json", {
        "legs": [{"id": "A:left>B", "points": [[0, 0], [0.05, 0], [1, 0]]}],
        "stations": [{"id": "HOME", "leg": "A:left>B", "pose": [0.5, 0.0, 0.0]}]})
    v = tv.view(st, maps)
    assert v["graph_revision"] == 2 and v["pass"] is None
    assert v["legs"] == [{"id": "A:left>B", "pts": [[0, 0], [1, 0]]}]
    assert v["stations"] == [{"id": "HOME", "x": 0.5, "y": 0.0, "leg": "A:left>B"}]
