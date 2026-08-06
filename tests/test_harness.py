from eval.harness import iou


def test_iou_identical_intervals_is_one():
    assert iou({"start": 0.0, "end": 10.0}, {"start": 0.0, "end": 10.0}) == 1.0


def test_iou_half_overlap():
    # overlap = 5, union = 10 + 10 - 5 = 15  ->  5/15 = 0.3333...
    result = iou({"start": 0.0, "end": 10.0}, {"start": 5.0, "end": 15.0})
    assert abs(result - (1.0 / 3.0)) < 1e-9


def test_iou_no_overlap_is_zero():
    assert iou({"start": 0.0, "end": 10.0}, {"start": 20.0, "end": 30.0}) == 0.0


from eval.harness import match_intervals


def test_match_perfect_one_to_one():
    preds = [{"start": 0.0, "end": 10.0}]
    gts = [{"start": 0.0, "end": 10.0}]
    result = match_intervals(preds, gts)
    assert len(result["matches"]) == 1
    assert result["missed"] == []
    assert result["false_pos"] == []


def test_match_one_prediction_cannot_claim_two_labels():
    # pred spans both labels; IoU with each is exactly 0.5 (>= threshold),
    # but greedy one-to-one must credit only ONE. The other is a miss.
    preds = [{"start": 0.0, "end": 20.0}]
    gts = [{"start": 0.0, "end": 10.0}, {"start": 10.0, "end": 20.0}]
    result = match_intervals(preds, gts)
    assert len(result["matches"]) == 1
    assert len(result["missed"]) == 1
    assert result["false_pos"] == []


def test_match_reports_miss_and_false_positive():
    preds = [{"start": 0.0, "end": 10.0}, {"start": 200.0, "end": 210.0}]
    gts = [{"start": 0.0, "end": 10.0}, {"start": 100.0, "end": 110.0}]
    result = match_intervals(preds, gts)
    assert len(result["matches"]) == 1
    assert result["missed"] == [1]      # gt at 100-110 unmatched
    assert result["false_pos"] == [1]   # pred at 200-210 unmatched


from eval.harness import detection_metrics


def test_detection_perfect_run():
    preds = [{"start": 0.0, "end": 10.0}]
    gts = [{"start": 0.0, "end": 10.0}]
    m = detection_metrics(preds, gts, source_duration_sec=600.0)
    assert m["recall"] == 1.0
    assert m["false_pos_per_10min"] == 0.0
    assert m["boundary_error_median_sec"] == 0.0


def test_detection_recall_and_false_positive_rate():
    # 2 labels, 1 matched -> recall 0.5.
    # 1 false prediction over 1200 s of source -> 1 / (1200/600) = 0.5 per 10 min.
    preds = [{"start": 0.0, "end": 10.0}, {"start": 200.0, "end": 210.0}]
    gts = [{"start": 0.0, "end": 10.0}, {"start": 100.0, "end": 110.0}]
    m = detection_metrics(preds, gts, source_duration_sec=1200.0)
    assert m["recall"] == 0.5
    assert m["false_pos_per_10min"] == 0.5


def test_detection_boundary_error_median():
    # matched pair off by 1 s at each end -> pooled errors [1, 1] -> median 1.0
    preds = [{"start": 1.0, "end": 11.0}]
    gts = [{"start": 0.0, "end": 10.0}]
    m = detection_metrics(preds, gts, source_duration_sec=600.0)
    assert m["boundary_error_median_sec"] == 1.0
