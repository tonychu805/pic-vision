import sys
sys.path.insert(0, ".")
import cv2
import numpy as np
import label_bounce_web as lb


def _video(path, n=60, fps=30, w=320, h=180):
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i in range(n):
        img = np.zeros((h, w, 3), np.uint8)
        cv2.putText(img, str(i), (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        out.write(img)
    out.release()


def test_decode_pads_the_clip_and_keeps_frame_numbers(tmp_path):
    v = tmp_path / "v.mp4"
    _video(v)
    clip = {"video": str(v), "start": 1.0, "end": 1.4}
    d = lb.decode_clip(clip)
    # padded by 1 s each side: frames 0..(1.4+1.0)*30 = 72, clipped to the 60 that exist
    assert d["first"] == 0 and len(d["jpegs"]) == 60
    assert d["w"] == 320 and d["scale"] == 1.0
    clip2 = {"video": str(v), "start": 1.5, "end": 1.6}
    assert lb.decode_clip(clip2)["first"] == 15


def test_labels_round_trip(tmp_path):
    p = str(tmp_path / "labels.jsonl")
    rows = {"a": {"clip": "a", "bounces": [{"frame": 3, "x": 1.0, "y": 2.0, "visible": True}], "complete": True}}
    lb.save_labels(rows, p)
    assert lb.load_labels(p) == rows
    assert lb.load_labels(str(tmp_path / "missing.jsonl")) == {}
