"""The redacted copy of a part kept after its reels (src/session_archive.py)."""
import json
import subprocess

import cv2
import numpy as np
import pytest

from src import session_archive as sa

W, H, FPS = 640, 360, 30
def person(x, y):
    return {"box": [x - 10, y, x + 10, y + 60], "kp": [[x, y + 6, 0.9]] * 5 + [[x, y + 20, 0.9]] * 12}


def write_video(path, frames):
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0",
                          "-pix_fmt", "yuv444p", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    assert p.wait() == 0


def read_frames(path):
    cap = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            return out
        out.append(f)


def checker(n):
    """Frames with high-detail texture everywhere, so a blur is measurable; frame i carries its index in a corner."""
    rng = np.random.default_rng(0)
    base = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
    frames = []
    for i in range(n):
        f = base.copy()
        cv2.putText(f, str(i), (300, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        frames.append(f)
    return frames


def detail(img):
    return float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def test_a_part_without_poses_for_every_other_frame_is_refused():
    with pytest.raises(sa.ArchiveRefused, match="no poses"):
        sa.check_pose_coverage({"0": [], "2": [], "6": []}, n_frames=8, stride=2)
    sa.check_pose_coverage({str(f): [] for f in range(0, 8, 2)}, n_frames=8, stride=2)


def test_a_frame_between_posed_frames_takes_both_neighbours_people():
    poses = {"10": [person(100, 50)], "12": [person(300, 50)]}
    assert len(sa.people_at(poses, 11)) == 2
    assert len(sa.people_at(poses, 10)) == 1


def test_head_boxes_reach_above_the_head_for_hair():
    (x0, y0, x1, y1), = sa.archive_boxes([person(320, 100)], [], scale=1.0, w=W, h=H)
    assert y0 < 100 - 10 and x0 < 310 and x1 > 330


def test_the_redacted_video_blurs_heads_only_and_keeps_every_frame(tmp_path):
    n = 20
    src = tmp_path / "part.mp4"
    write_video(src, checker(n))
    poses = {str(f): [person(320, 120)] for f in range(0, n, 2)}
    dst = tmp_path / "archive.mp4"

    res = sa.redact_video(str(src), str(dst), poses, out_height=H, workers=3, encoders=("libx264",))

    assert res["frames"] == n
    out = read_frames(dst)
    orig = checker(n)
    assert len(out) == n
    for i in (0, 7, 19):  # posed, between posed frames, last
        head = (slice(100, 135), slice(305, 335))
        court = (slice(250, 300), slice(240, 280))
        outside = (slice(150, 250), slice(20, 120))
        assert detail(out[i][head]) < 0.2 * detail(orig[i][head]), f"head blurred in frame {i}"
        assert detail(out[i][outside]) > 0.5 * detail(orig[i][outside]), f"off-court left sharp in frame {i}"
        assert detail(out[i][court]) > 0.5 * detail(orig[i][court]), f"court kept sharp in frame {i}"


def test_frames_stay_in_order_across_workers(tmp_path):
    n = 24
    frames = [np.full((H, W, 3), 8 * i, np.uint8) for i in range(n)]
    src = tmp_path / "ramp.mp4"
    write_video(src, frames)
    dst = tmp_path / "archive.mp4"
    sa.redact_video(str(src), str(dst), {str(f): [] for f in range(0, n, 2)}, out_height=H, workers=4,
                    encoders=("libx264",))
    centre = [int(f[180, 320].mean()) for f in read_frames(dst)]
    assert len(centre) == n
    steps = [b - a for a, b in zip(centre, centre[1:])]
    assert all(4 <= d <= 12 for d in steps), f"a frame repeated or skipped at a worker boundary: {centre}"


def test_a_failed_encode_leaves_no_file(tmp_path):
    src = tmp_path / "part.mp4"
    write_video(src, checker(6))
    dst = tmp_path / "archive.mp4"
    with pytest.raises(sa.ArchiveRefused):
        sa.redact_video(str(src), str(dst), {str(f): [] for f in range(0, 6, 2)}, out_height=H, workers=2,
                        encoders=("no_such_encoder",))
    assert not dst.exists()
