import quality_dashboard as qd


def test_best_threshold_balanced_acc_perfectly_separable():
    values = [1, 2, 3, 10, 11, 12]
    grades = [2, 2, 2, 1, 1, 1]
    bal, t = qd.best_threshold_balanced_acc(values, grades)
    assert bal == 1.0
    assert 3 < t < 10


def test_best_threshold_balanced_acc_no_signal():
    values = [1, 2, 3, 4, 5, 6]
    grades = [1, 2, 1, 2, 1, 2]     # interleaved, nothing separates them
    bal, _ = qd.best_threshold_balanced_acc(values, grades)
    assert bal <= 0.6                # can't do much better than chance


def test_zscore_within_session_normalizes_independently():
    rows = [
        {"session": "a", "duration": 10.0, "grade": 1},
        {"session": "a", "duration": 20.0, "grade": 2},
        {"session": "b", "duration": 100.0, "grade": 1},
        {"session": "b", "duration": 200.0, "grade": 2},
    ]
    scored = qd.zscore_within_session(rows, ["duration"])
    by_session = {}
    for r in scored:
        by_session.setdefault(r["session"], []).append(r["combined"])
    # each session's two points are equidistant from its own mean -> same |z|
    assert abs(by_session["a"][0]) == abs(by_session["a"][1])
    assert abs(by_session["b"][0]) == abs(by_session["b"][1])
    assert abs(by_session["a"][0] - by_session["b"][0]) < 1e-9


def test_score_combination_empty_active_returns_no_sessions():
    rows = [{"session": "a", "grade": 1, "duration": 10.0}]
    result = qd.score_combination(rows, [])
    assert result == {"per_session": {}, "active": []}


def test_score_combination_flags_low_confidence():
    rows = (
        [{"session": "a", "grade": 1, "duration": float(i)} for i in range(2)] +
        [{"session": "a", "grade": 2, "duration": float(i)} for i in range(10, 20)]
    )
    result = qd.score_combination(rows, ["duration"])
    assert result["per_session"]["a"]["n_grade1"] == 2
    assert result["per_session"]["a"]["low_confidence"] is True


def test_score_combination_not_low_confidence_with_enough_examples():
    rows = (
        [{"session": "a", "grade": 1, "duration": float(i)} for i in range(6)] +
        [{"session": "a", "grade": 2, "duration": float(i)} for i in range(10, 20)]
    )
    result = qd.score_combination(rows, ["duration"])
    assert result["per_session"]["a"]["low_confidence"] is False
