"""Held-out brickwall-SEMI: rallies found whole-frame vs view box, IoU >= 0.5 against hand labels (2026-11-21)."""
import json, sys, subprocess
from pathlib import Path
REPO = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(Path(__file__).parent))
from src.view_box import calib_for_box, video_crop
from src.court_crop import court_crop_box
from src.rallies import detect_candidates
import view_box_marks_eval as R

VIDEO = "/home/tonychu/repository/pic-vision/videos/brickwall_30fps.mp4"
CALIB = json.load(open("/home/tonychu/repository/pic-vision/calib/brickwall_30fps_calib.json"))
_wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", VIDEO],
                     capture_output=True, text=True, check=True).stdout.strip().split(",")
VW, VH = int(_wh[0]), int(_wh[1])
# The pod treats a calibration without a resolution as made at the video's own size.
CALIB.setdefault("calibration_resolution", [VW, VH])
LABELS = [json.loads(l) for l in open("/home/tonychu/repository/pic-vision/eval/labels/brickwall_30fps.jsonl")]
LABELS = [(l["start"], l["end"]) for l in LABELS]

def iou(a, b):
    i = max(0.0, min(a[1], b[1]) - max(a[0], b[0])); u = max(a[1], b[1]) - min(a[0], b[0])
    return i / u if u > 0 else 0.0

def score(segs):
    used, tp = set(), 0
    for s in segs:
        best = max(((iou(s, l), k) for k, l in enumerate(LABELS) if k not in used), default=(0, None))
        if best[0] >= 0.5: used.add(best[1]); tp += 1
    return tp, len(segs), len(LABELS)

for name, box in (("bw30_whole", None), ("bw30_box127", court_crop_box(CALIB, (VH, VW), margin=0.08, airspace=0.9))):
    calib = dict(CALIB)
    if box: calib["view_box"] = dict(zip(("x0", "y0", "x1", "y1"), box))
    vid, csvp = OUT / f"{name}.mp4", OUT / f"{name}.csv"
    crop = video_crop(calib, (VW, VH))
    boxed = calib_for_box(calib)
    if not csvp.exists():
        vf = ["-vf", "crop={}:{}:{}:{}".format(*crop)] if crop else []
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", VIDEO, *vf, "-map", "0:v:0", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
                        "-vsync", "cfr", "-r", "30", str(vid)], check=True)
        R.infer(vid, boxed, csvp)
    cp = csvp.with_suffix(".calib.json"); json.dump(boxed, open(cp, "w"))
    det = detect_candidates(str(vid), str(csvp), str(cp), occlusion_bridge=True)
    segs = [(s[0], s[1]) if not isinstance(s, dict) else (s["start"], s["end"]) for s in det["segments"]]
    tp, n, nl = score(segs)
    frames = sum(1 for _ in open(csvp)) - 1; found = sum(1 for l in open(csvp) if l.split(",")[1] == "1")
    zoom = VW / (box[2] - box[0]) if box else 1.0
    print(f"{name:9} zoom {zoom:4.2f}x crop {crop}  ball in {found/frames:5.1%}  crossings {len(det['times_crossed'])}  "
          f"rallies found {n}, matched {tp} of {nl} labels at IoU>=0.5  precision {tp/max(n,1):.2f} recall {tp/nl:.2f}", flush=True)
