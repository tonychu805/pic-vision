from label import load_rallies, save_rallies


def test_save_rallies_sorts_and_renumbers(tmp_path):
    p = tmp_path / "labels.jsonl"
    save_rallies([{"start": 30.0, "end": 35.0, "duration": 5.0},
                  {"start": 10.0, "end": 12.0, "duration": 2.0}], str(p))
    rs = load_rallies(str(p))
    assert [r["start"] for r in rs] == [10.0, 30.0]      # sorted by start
    assert [r["rally_id"] for r in rs] == [1, 2]          # renumbered


def test_load_rallies_absent_is_empty(tmp_path):
    assert load_rallies(str(tmp_path / "nope.jsonl")) == []


def test_quality_grade_round_trips_through_save(tmp_path):
    # review-mode grades (quality 1/2) must survive save/load; ungraded stays bare
    p = tmp_path / "labels.jsonl"
    save_rallies([{"start": 1.0, "end": 2.0, "duration": 1.0, "quality": 1},
                  {"start": 5.0, "end": 6.0, "duration": 1.0}], str(p))
    rs = load_rallies(str(p))
    assert rs[0]["quality"] == 1
    assert "quality" not in rs[1]


def test_dropping_then_saving_removes_and_renumbers(tmp_path):
    # the keep/drop review relies on: save the kept subset, which renumbers
    p = tmp_path / "labels.jsonl"
    save_rallies([{"start": 1.0, "end": 2.0, "duration": 1.0},
                  {"start": 5.0, "end": 6.0, "duration": 1.0},
                  {"start": 9.0, "end": 10.0, "duration": 1.0}], str(p))
    rs = load_rallies(str(p))
    kept = [rs[0], rs[2]]                                  # drop the middle
    save_rallies(kept, str(p))
    out = load_rallies(str(p))
    assert [r["start"] for r in out] == [1.0, 9.0]
    assert [r["rally_id"] for r in out] == [1, 2]
