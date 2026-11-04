from amr_mission.run_trace import HEADER, RunTrace


def test_one_file_per_run_with_a_header_and_rows(tmp_path):
    t = RunTrace(str(tmp_path))
    t.write("r1", 1, "s1", 0.5, "")
    t.write("r1", 1, "s2", 0.25, "")
    t.write("r2", 1, "s1", 0.5, "")
    t.close()
    lines = (tmp_path / "r1.csv").read_text().splitlines()
    assert lines[0] == HEADER and len(lines) == 3
    assert lines[2].endswith(",r1,1,s2,0.2500,")
    assert (tmp_path / "r2.csv").exists()


def test_the_oldest_runs_are_pruned(tmp_path):
    t = RunTrace(str(tmp_path), keep=2)
    for r in ("a", "b", "c"):
        t.write(r, 1)
    t.close()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["b.csv", "c.csv"]


def test_an_unwritable_directory_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    t = RunTrace(str(blocker / "sub"))
    t.write("r1", 1)  # must not raise: evidence never stops the vehicle
    t.close()
