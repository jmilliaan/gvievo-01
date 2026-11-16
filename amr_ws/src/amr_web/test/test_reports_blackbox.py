"""WP-P6: the report zip carries the newest black-box snapshots, and only those."""

import os
import zipfile

from amr_web import reports


def test_the_report_carries_the_two_newest_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "_journal_of", lambda unit: "(journal)\n")
    bb = tmp_path / "blackbox" / "bb-20261116-100000"
    bb.mkdir(parents=True)
    for i, name in enumerate(("bb_0.mcap", "bb_1.mcap", "bb_2.mcap")):
        p = bb / name
        p.write_bytes(b"m" * (i + 1))
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    (bb / "metadata.yaml").write_text("x")
    assert [os.path.basename(p) for p in reports.blackbox_files(str(tmp_path))] == ["bb_2.mcap", "bb_1.mcap"]
    name = reports.build(str(tmp_path), {}, [], {}, [])
    with zipfile.ZipFile(tmp_path / "reports" / name) as z:
        got = sorted(n for n in z.namelist() if n.startswith("blackbox/"))
    assert got == ["blackbox/bb-20261116-100000/bb_1.mcap", "blackbox/bb-20261116-100000/bb_2.mcap"]


def test_no_black_box_no_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "_journal_of", lambda unit: "(journal)\n")
    assert reports.blackbox_files(str(tmp_path)) == []
    name = reports.build(str(tmp_path), {}, [], {}, [])
    with zipfile.ZipFile(tmp_path / "reports" / name) as z:
        assert not [n for n in z.namelist() if n.startswith("blackbox/")]
