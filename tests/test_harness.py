from eval.harness import iou


def test_iou_identical_intervals_is_one():
    assert iou({"start": 0.0, "end": 10.0}, {"start": 0.0, "end": 10.0}) == 1.0


def test_iou_half_overlap():
    # overlap = 5, union = 10 + 10 - 5 = 15  ->  5/15 = 0.3333...
    result = iou({"start": 0.0, "end": 10.0}, {"start": 5.0, "end": 15.0})
    assert abs(result - (1.0 / 3.0)) < 1e-9


def test_iou_no_overlap_is_zero():
    assert iou({"start": 0.0, "end": 10.0}, {"start": 20.0, "end": 30.0}) == 0.0
