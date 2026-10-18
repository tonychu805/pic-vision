import sys

sys.path.insert(0, "scripts")
from eval_bounce_zones import near_line, zone


def test_zones_split_each_side_at_the_kitchen_line():
    assert zone(-3.0) == "near_deep" and zone(14.9) == "near_deep"
    assert zone(15.0) == "near_kitchen" and zone(21.9) == "near_kitchen"
    assert zone(22.0) == "far_kitchen" and zone(28.9) == "far_kitchen"
    assert zone(29.0) == "far_deep" and zone(50.0) == "far_deep"


def test_near_line_flags_marks_within_one_foot():
    assert near_line(14.2) and near_line(22.9) and near_line(29.5)
    assert not near_line(10.0) and not near_line(25.5)
