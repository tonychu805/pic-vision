"""View-box ball-model comparison on PDSC Court 3 part 9 marks (2026-11-21).

Conditions, all production model (k14 torch) and production cut 0.5:
  whole  - the pod today: whole frame
  boxN   - a view box, cropped in the convert step exactly as pod_driver does (video_crop + calib_for_box)
  court  - --crop-to-court (the 2026-11-01 court crop, off in production since 11-12), reference
Scored like scripts/eval_sam2_ball_track.py: marks are in the 1104x621 view at (432,300) of the 1080p frame.
"""
import csv, json, subprocess, sys, os
from pathlib import Path
import numpy as np

REPO = Path(sys.argv[1]); OUT = Path(sys.argv[2])
sys.path.insert(0, str(REPO))
from src.view_box import calib_for_box, video_crop, view_box
from src.court_crop import court_crop_box

PY = "/home/tonychu/repository/pic-vision/.venv/bin/python"
VIDEO = "/home/tonychu/repository/pic-vision/videos/pdsc-fieldtest-nov2026/d17725d4-72b0-4f7b-882a-7176bf2b6f30/2026-11-01T03-12-08-425Z/session-009.mkv"
CALIB = json.load(open("/home/tonychu/repository/pic-vision/calib/pdsc_court3_calib.json"))
WEIGHTS = "/mnt/fast_scratch/pic-vision-scratch/workstation-cache/c0f2e9534ae80dfc0677998d84f900ab/tracknet_k14_epoch19.pt"
MARKS = [json.loads(l) for l in open("/home/tonychu/repository/pic-vision/eval/labels/pdsc_court3_20261101_ball_marks.jsonl")]
MARKS = [m for m in MARKS if m.get("set") == "seq9"]
VIEW = (432, 300)
CAL_W, CAL_H = CALIB["calibration_resolution"]
S = 1080 / CAL_H  # calibration px -> 1080p px

def ff(args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)

def convert(crop, out):
    vf = ["-vf", "crop={}:{}:{}:{}".format(*crop)] if crop else []
    ff(["-err_detect", "ignore_err", "-i", VIDEO, *vf, "-map", "0:v:0", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
        "-vsync", "cfr", "-r", "30", str(out)])

def infer(video, calib, out_csv, extra=()):
    cp = out_csv.with_suffix(".calib.json"); json.dump(calib, open(cp, "w"))
    subprocess.run([PY, str(REPO / "scripts/pod_infer.py"), "--video", str(video), "--model", WEIGHTS, "--output", str(out_csv),
                    "--calib", str(cp), "--heat-threshold", "0.5", *extra], check=True, cwd=REPO, stdout=subprocess.DEVNULL)

def load_dets(csv_path, origin_cal=(0.0, 0.0)):
    """frame -> (x, y) in 1080p full-frame pixels."""
    d = {}
    for r in csv.DictReader(open(csv_path)):
        if r["Visibility"] == "1":
            d[int(r["Frame"])] = ((float(r["X"]) + origin_cal[0]) * S, (float(r["Y"]) + origin_cal[1]) * S)
    return d

def far_baseline_y_1080(x1080):
    h_inv = np.linalg.inv(np.array(CALIB["homography"]))
    (ax, ay), (bx, by) = [(v[0] / v[2] * S, v[1] / v[2] * S) for v in (h_inv @ [0, CALIB["court_size_ft"][1], 1], h_inv @ [CALIB["court_size_ft"][0], CALIB["court_size_ft"][1], 1])]
    return ay + (by - ay) * (x1080 - ax) / (bx - ax)

def score(dets, radius):
    wall = court = wall_n = court_n = ghost = 0
    for m in MARKS:
        f = m["frame"]; d = dets.get(f)
        if m["x"] is None:
            ghost += d is not None; continue
        mx, my = m["x"] + VIEW[0], m["y"] + VIEW[1]
        is_wall = my < far_baseline_y_1080(mx)
        ok = d is not None and np.hypot(d[0] - mx, d[1] - my) <= radius
        if is_wall: wall_n += 1; wall += ok
        else: court_n += 1; court += ok
    return wall, wall_n, court, court_n, ghost

def run(name, crop_cal=None, extra=()):
    OUT.mkdir(parents=True, exist_ok=True)
    calib = dict(CALIB)
    if crop_cal:
        calib["view_box"] = dict(zip(("x0", "y0", "x1", "y1"), crop_cal))
    vid = OUT / f"{name}.mp4"; csvp = OUT / f"{name}.csv"
    crop = video_crop(calib, (1920, 1080))
    if not csvp.exists():
        convert(crop, vid)
        infer(vid, calib_for_box(calib), csvp, extra)
    origin = view_box(calib)[:2] if crop_cal else (0.0, 0.0)
    dets = load_dets(csvp, origin)
    frames = sum(1 for _ in open(csvp)) - 1
    zoom = CAL_W / (crop_cal[2] - crop_cal[0]) if crop_cal else 1.0
    res = {r: score(dets, r) for r in (11, 20)}
    print(f"{name:7} zoom {zoom:4.2f}x crop {crop}  ball in {len(dets)/frames:5.1%} of frames  "
          + "  ".join(f"@{r}px wall {w}/{wn} court {c}/{cn} ghosts {g}/26" for r, (w, wn, c, cn, g) in res.items()), flush=True)

def suggested_box(margin, airspace):
    # The view box the calibration screen would suggest: court + room behind the baselines + lob airspace, 16:9.
    x0, y0, x1, y1 = court_crop_box(CALIB, (CAL_H, CAL_W), margin=margin, airspace=airspace)
    return (x0, y0, x1, y1)

if __name__ == "__main__":
    run("whole")
    run("box130", suggested_box(0.08, 0.9))
    run("box159", suggested_box(0.04, 0.7))
    run("court", extra=("--crop-to-court",))
