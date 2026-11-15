import os

import cv2
import numpy as np
import pytest

os.environ.setdefault("JOB_ID", "test-job-id")
os.environ.setdefault("JOB_TOKEN", "test-token")
os.environ.setdefault("BUCKET", "test-bucket")
os.environ.setdefault("OUTPUT_BUCKET", "test-output-bucket")
os.environ.setdefault("BRAND_ID", "test-brand-id")

from cloud_pipeline import pod_driver  # noqa: E402
from src.jev_sheet import contact_sheet, keep_polygon, redact  # noqa: E402

# A camera whose whole 96x54 frame is the 20 x 44 ft court: no off-court blur in the content tests.
CALIB = {"homography": [[20 / 96, 0, 0], [0, 44 / 54, 0], [0, 0, 1]], "calibration_resolution": [96, 54]}


@pytest.fixture
def video(tmp_path):
    path = str(tmp_path / "v.mp4")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 54))
    for i in range(200):
        w.write(np.full((54, 96, 3), i, np.uint8))
    w.release()
    return path


def clips(n):
    return [{"start": 2.0 + i, "end": 8.0 + i} for i in range(1, n + 1)]


class Reply:
    def __init__(self, status=200, body=None, bad_json=False):
        self.status_code, self.body, self.bad_json = status, body, bad_json

    def json(self):
        if self.bad_json:
            raise ValueError("not json")
        return self.body


def test_contact_sheet_is_a_decodable_jpeg_of_the_validated_size(video):
    jpg = contact_sheet(video, 2.0, 12.0, CALIB)
    im = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert im.shape == (1323, 1568, 3)


def test_contact_sheet_shows_the_rally_not_the_whole_video(video):
    def tile_means(start, end):
        im = cv2.imdecode(np.frombuffer(contact_sheet(video, start, end, CALIB), np.uint8), cv2.IMREAD_GRAYSCALE)
        return [int(im[300 + (i // 2) * 441, 700 + (i % 2) * 784]) for i in range(6)]
    early, late = tile_means(0.0, 6.0), tile_means(12.0, 18.0)
    assert early == sorted(early) and late == sorted(late)
    assert max(early) < min(late)


def test_valid_answers_come_back_for_every_rally(video, monkeypatch):
    sent = []

    def post(url, data, headers, timeout):
        sent.append((url, headers, len(data)))
        return Reply(200, {"real": 0.3 if len(sent) % 2 else 0.9, "kind": "real_point"})
    monkeypatch.setattr(pod_driver.requests, "post", post)
    found, stats = pod_driver.jev_checks(video, clips(12), CALIB)
    assert sorted(found) == sorted(pod_driver.rally_key(c["start"], c["end"]) for c in clips(12))
    assert len(sent) == 12
    url, headers, size = sent[0]
    assert url.endswith(f"/api/runner/jobs/{pod_driver.JOB_ID}/jev")
    assert headers["Authorization"] == f"Bearer {pod_driver.JOB_TOKEN}" and headers["Content-Type"] == "image/jpeg"
    assert size < 2_000_000
    assert stats["checked"] == 12 and stats["failed"] == 0
    assert stats["flagged"] == sum(a["real"] < pod_driver.JEV_CUT for a in found.values()) == 6


def raises(*a, **k):
    raise OSError("connection reset")


@pytest.mark.parametrize("post", [
    lambda *a, **k: Reply(503, {"error": "down"}),
    raises,
    lambda *a, **k: Reply(bad_json=True),
    lambda *a, **k: Reply(200, {"real": 1.7, "kind": "real_point"}),
    lambda *a, **k: Reply(200, {"real": 0.5}),
    lambda *a, **k: Reply(200, {"real": "high", "kind": "real_point"}),
], ids=["503", "raises", "bad-json", "out-of-range", "no-kind", "non-numeric"])
def test_jev_trouble_leaves_every_clip_unchecked(video, monkeypatch, post):
    monkeypatch.setattr(pod_driver.requests, "post", post)
    found, stats = pod_driver.jev_checks(video, clips(4), CALIB)
    assert found == {}
    assert stats["checked"] == 0 and stats["failed"] == 4 and stats["flagged"] == 0


def test_a_clip_whose_video_cannot_be_read_fails_open(tmp_path, monkeypatch):
    monkeypatch.setattr(pod_driver.requests, "post", lambda *a, **k: Reply(200, {"real": 0.9, "kind": "x"}))
    found, stats = pod_driver.jev_checks(str(tmp_path / "missing.mp4"), clips(2), CALIB)
    assert found == {} and stats["failed"] == 2


def test_one_failed_clip_does_not_lose_the_others(video, monkeypatch):
    calls = iter(range(100))

    def post(*a, **k):
        return Reply(503) if next(calls) == 0 else Reply(200, {"real": 0.8, "kind": "real_point"})
    monkeypatch.setattr(pod_driver.requests, "post", post)
    found, stats = pod_driver.jev_checks(video, clips(3), CALIB)
    assert len(found) == 2 and stats["checked"] == 2 and stats["failed"] == 1


def test_a_verdict_finds_its_clip_by_the_rally_times():
    """The clip's rally_start/rally_end are the segment's own floats (top_rallies_reel.py), so the keys meet."""
    seg = {"start": 12.366666666666667, "end": 30.03333333333333}
    clip = {"rally_start": seg["start"], "rally_end": seg["end"], "start": seg["start"] - 3.0, "end": seg["end"] + 3.0}
    assert pod_driver.rally_key(clip["rally_start"], clip["rally_end"]) == pod_driver.rally_key(seg["start"], seg["end"])


def test_in_background_returns_the_value_or_raises_the_error():
    assert pod_driver.in_background(lambda a, b: a + b, 2, 3)() == 5

    def boom():
        raise ValueError("no")
    with pytest.raises(ValueError):
        pod_driver.in_background(boom)()


def _noise(h=200, w=400):
    return np.random.default_rng(0).integers(0, 256, (h, w, 3), dtype=np.uint8)


def test_redaction_blurs_off_the_court_and_keeps_the_court():
    frame = _noise()
    court = np.array([[[100, 50]], [[300, 50]], [[300, 150]], [[100, 150]]], np.int32)
    out = redact(frame, court, [], [])
    assert (out[60:140, 110:290] == frame[60:140, 110:290]).all(), "the court must be untouched"
    assert out[:40].std() < frame[:40].std() / 3, "off-court must be blurred"


def test_redaction_blurs_a_players_head_and_a_detected_face():
    frame = _noise()
    court = np.array([[[0, 0]], [[399, 0]], [[399, 199]], [[0, 199]]], np.int32)
    person = {"box": [180, 40, 220, 160], "kp": [[200, 55, 0.9]] * 5 + [[0, 0, 0]] * 12}
    out = redact(frame, court, [person], [(20, 20, 60, 60)])
    assert out[45:65, 190:210].std() < frame[45:65, 190:210].std() / 3, "head must be blurred"
    assert out[25:55, 25:55].std() < frame[25:55, 25:55].std() / 3, "face must be blurred"
    assert (out[120:160, 300:380] == frame[120:160, 300:380]).all(), "the rest of the court is untouched"


def test_the_keep_area_covers_the_court_and_room_behind_the_baselines_but_not_far_beyond():
    calib = {"homography": [[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]], "calibration_resolution": [1000, 1000]}   # 10 px per ft
    poly = keep_polygon(calib, 1000, 1000)
    inside = lambda x, y: cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0
    assert inside(100, 220)                     # centre of the court (10, 22 ft)
    assert inside(100, 440 + 80)                # 8 ft behind a baseline: where a ball machine stands
    assert not inside(100 + 200 + 60 + 50, 220) # 11 ft past a sideline: the next court
