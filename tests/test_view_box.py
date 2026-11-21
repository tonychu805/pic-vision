import numpy as np
import pytest

from src.ball import net_line_y
from src.calib import court_wedge
from src.view_box import calib_for_box, video_crop, view_box

# A real production calibration (PGC camera, 2026-11-20), 1920x1080.
CALIB = {
    "net_y_ft": 22,
    "court_size_ft": [20, 44],
    "calibration_resolution": [1920, 1080],
    "homography": [[-0.027639601887973597, -0.03353194525989228, 37.208033841293464],
                   [-0.000007439551018679279, 0.042808163164493915, -41.579940064998574],
                   [0.000014535704064525728, -0.003348933629733811, 1]],
    "image_points": [[173.3, 969.5], [1790.7, 977.8], [796.8, 452.6], [1160.9, 454.7],
                     [606.4, 611.7], [1347.1, 611.7], [731.9, 507.0], [1225.8, 507.0],
                     [972.6, 971.6], [978.8, 452.6], [976.8, 605.4], [974.7, 509.1]],
    "net_image_points": [[635.7, 456.8], [1307.4, 458.9]],
    "court_points_ft": [[0, 0], [20, 0], [0, 44], [20, 44], [0, 15], [20, 15], [0, 29], [20, 29],
                        [10, 0], [10, 44], [10, 15], [10, 29]],
}
BOX = {"x0": 160, "y0": 90, "x1": 1760, "y1": 990}  # 1600x900, 16:9, 1.2x


def boxed(box=BOX):
    return {**CALIB, "view_box": box}


def to_court(h, pt):
    v = np.asarray(h, dtype=float) @ [pt[0], pt[1], 1.0]
    return v[:2] / v[2]


def test_no_box_leaves_the_calibration_alone():
    assert view_box(CALIB) is None
    assert calib_for_box(CALIB) is CALIB
    assert video_crop(CALIB, (1280, 720)) is None


def test_boxed_points_shift_by_the_origin_and_round_trip():
    out = calib_for_box(boxed())
    back = np.asarray(out["image_points"]) + [160, 90]
    assert np.allclose(back, CALIB["image_points"])
    assert np.allclose(np.asarray(out["net_image_points"]) + [160, 90], CALIB["net_image_points"])
    assert out["calibration_resolution"] == [1600, 900]
    assert "view_box" not in out
    assert "view_box" in boxed(), "the stored calibration is not changed"


def test_every_pixel_lands_on_the_same_court_spot():
    out = calib_for_box(boxed())
    for old, new in zip(CALIB["image_points"], out["image_points"]):
        assert np.allclose(to_court(CALIB["homography"], old), to_court(out["homography"], new), atol=1e-9)


def test_the_net_line_and_court_gate_move_with_the_box():
    out = calib_for_box(boxed())
    assert net_line_y(out) == pytest.approx(net_line_y(CALIB) - 90, abs=1e-6)
    old_gate, new_gate = court_wedge(CALIB), court_wedge(out)
    points = [(x, y) for x in range(0, 1920, 40) for y in range(0, 1080, 30)]
    assert any(old_gate(x, y) for x, y in points) and not all(old_gate(x, y) for x, y in points)
    assert all(old_gate(x, y) == new_gate(x - 160, y - 90) for x, y in points)


def test_a_point_outside_the_box_keeps_working_coordinates():
    tight = {"x0": 400, "y0": 300, "x1": 1520, "y1": 930}
    out = calib_for_box(boxed(tight))
    near_left = out["image_points"][0]  # (173, 969): left of and below the box
    assert near_left[0] < 0 and near_left[1] > 630
    assert np.allclose(to_court(out["homography"], near_left), to_court(CALIB["homography"], CALIB["image_points"][0]))


def test_crop_scales_to_the_uploaded_video_and_stays_even():
    assert video_crop(boxed(), (1920, 1080)) == (1600, 900, 160, 90)
    assert video_crop(boxed(), (1280, 720)) == (1066, 600, 106, 60)
    w, h, x, y = video_crop(boxed({"x0": 1, "y0": 1, "x1": 1919, "y1": 1079}), (1281, 721))
    assert all(v % 2 == 0 for v in (w, h, x, y))
    assert x + w <= 1281 and y + h <= 721


def test_a_box_at_the_frame_edge_stays_inside():
    edge = {"x0": 320, "y0": 180, "x1": 1920, "y1": 1080}
    assert video_crop(boxed(edge), (1280, 720)) == (1068, 600, 212, 120)  # reaches the right edge exactly


def test_an_empty_or_outside_box_is_refused():
    for bad in ({"x0": 500, "y0": 100, "x1": 500, "y1": 900},
                {"x0": -10, "y0": 0, "x1": 1600, "y1": 900},
                {"x0": 400, "y0": 300, "x1": 2000, "y1": 1000}):
        with pytest.raises(ValueError):
            calib_for_box(boxed(bad))


def test_ffmpeg_crops_a_720p_upload_to_the_box(tmp_path):
    # The dual-stream case: calibrated at 1080p, the pod gets the 720p sub-stream.
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=1",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    w, h, x, y = video_crop(boxed(), (1280, 720))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"crop={w}:{h}:{x}:{y}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout.strip()
    assert probe == "1066,600"
    # The cropped video and the boxed calibration agree on proportions (court_crop and the hit finder scale by them).
    cw, ch = calib_for_box(boxed())["calibration_resolution"]
    assert abs(1066 / cw - 600 / ch) < 0.002
