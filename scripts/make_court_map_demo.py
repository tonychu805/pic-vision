"""Court map demo: camera view beside a 2D court map of player feet and bounce picks (2026-10-18, PIC-226).
Ball flight is not drawn on the map (a ball in the air can't be placed on the floor from one camera); only
floor contacts: bounces and feet. Internal review of third-party venue footage; do not share.

Footage, fixed in advance and not chosen by looking: chunk 3c (eda301d9 2026-09-26 05:38 s000, the clean court),
the first minute of its labelled stretch (chunk frames 0-1799, source 2:00-3:00). Bounce picks: the finder on the
tiled k14 detections (cache/bounce_pilot/chunk3c...tile.csv), as in eval_bounce_zones.py. Players: yolov8x-pose
boxes, feet = box bottom centre through the calibration homography, kept when on the court (x -2..22, y -6..50 ft).
Colours (from the operator's exhaustive bounce marks, same matching as the tests: +-3 frames, 15 px):
  green dot  a pick that matches a marked bounce      red dot  a pick with no marked bounce (false dot)
  white ring a marked bounce the finder missed         blue dots players' feet
Run: .venv/bin/python scripts/make_court_map_demo.py OUT.mp4 [START_FRAME N_FRAMES]
"""
import json, math, subprocess, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import cv2, numpy as np
from src.bounce_eval import project
import eval_bounce_recovery as E

LAB = "eval/labels/bounces/cvat_eda301d9_0926T0538_s000_120-360.json"
CSV = "cache/bounce_pilot/chunk3c_eda301d9_0538_s000.tile.csv"
CALIB = "cache/pgc_fieldtest/7358ef3f-6a41-4abe-b431-807eba7bc9f1.calib.json"
PX, M = 20, 70                       # map: px per foot, margin px
MW, MH = 20 * PX + 2 * M, 1080
OY = (MH - 44 * PX) // 2             # vertical offset so the 44 ft court is centred
GREEN, RED, WHITE, BLUE, AMBER = (90, 220, 110), (70, 70, 240), (255, 255, 255), (255, 170, 60), (40, 190, 255)
SHOW = 60                            # frames a bounce stays on screen


def to_map(x, y):
    return int(M + x * PX), int(OY + (44 - y) * PX)   # near baseline (y = 0) at the bottom, like the camera


def court_base():
    im = np.full((MH, MW, 3), (38, 92, 60), np.uint8)
    cv2.rectangle(im, to_map(-3, -4), to_map(23, 48), (60, 60, 60), -1)
    cv2.rectangle(im, to_map(0, 0), to_map(20, 44), (52, 120, 78), -1)
    cv2.rectangle(im, to_map(0, 15), to_map(20, 29), (92, 160, 130), -1)          # kitchen
    for a, b in (((0, 0), (20, 0)), ((0, 44), (20, 44)), ((0, 0), (0, 44)), ((20, 0), (20, 44)),
                 ((0, 15), (20, 15)), ((0, 29), (20, 29)), ((10, 0), (10, 15)), ((10, 29), (10, 44))):
        cv2.line(im, to_map(*a), to_map(*b), WHITE, 2, cv2.LINE_AA)
    cv2.line(im, to_map(-1, 22), to_map(21, 22), (230, 230, 230), 4, cv2.LINE_AA)  # net
    for txt, y in (("FAR", 46.2), ("NEAR", -2.8)):
        cv2.putText(im, txt, (to_map(0, y)[0], to_map(0, y)[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2, cv2.LINE_AA)
    return im


def main(out, start=0, n=1800):
    from ultralytics import YOLO
    lab = json.load(open(LAB)); off = lab["source_frame_offset"]
    video = json.load(open(
        "cache/scale/eda301d9_2026-09-26T05-38-19_session-000.meta.json"))["path"]
    H, raw, tracked, cands = E.clip_points({"calib": CALIB, "csv": CSV})
    marks = [(b["frame"], b["x"], b["y"]) for b in lab["bounces"]]
    near = lambda c, b: abs(c - b[0]) <= 3 and math.hypot(cands[c][0] - b[1], cands[c][1] - b[2]) <= 15
    picks = {c: any(near(c, b) for b in marks) for c in cands}
    missed = [b for b in marks if not any(near(c, b) for c in cands)]
    sel = lambda f: start <= f < start + n
    print(f"window: picks {sum(map(sel, picks))} (real {sum(v for c, v in picks.items() if sel(c))}), "
          f"marks {sum(sel(b[0]) for b in marks)}, missed {sum(sel(b[0]) for b in missed)}")
    model = YOLO("yolov8x-pose.pt"); base = court_base(); feet_hist = []
    cap = cv2.VideoCapture(video); cap.set(cv2.CAP_PROP_POS_FRAMES, off + start)
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{1920 + MW}x1080",
                          "-r", "30", "-i", "-", "-vf", "scale=2400:-2", "-c:v", "libx264", "-crf", "22", "-preset", "slow",
                          "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    for k in range(n):
        ok, im = cap.read()
        if not ok: break
        f = start + k; mp_ = base.copy()
        # players
        r = model.predict(im, imgsz=1280, conf=0.25, classes=[0], verbose=False)[0]
        feet = []
        for b in r.boxes.xyxy.cpu().numpy():
            cx, cy = project(H, (b[0] + b[2]) / 2, b[3])
            if -2 <= cx <= 22 and -6 <= cy <= 50:
                feet.append((cx, cy)); cv2.rectangle(im, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), BLUE, 2, cv2.LINE_AA)
        feet_hist = (feet_hist + [feet])[-20:]
        for i, fs in enumerate(feet_hist[:-1]):
            for x, y in fs: cv2.circle(mp_, to_map(x, y), 3, tuple(int(c * 0.6) for c in BLUE), -1, cv2.LINE_AA)
        for x, y in feet: cv2.circle(mp_, to_map(x, y), 11, BLUE, -1, cv2.LINE_AA); cv2.circle(mp_, to_map(x, y), 11, WHITE, 2, cv2.LINE_AA)
        # ball trail on the camera view only
        pts = [(i, *tracked[i]) for i in range(f - 18, f + 1) if i in tracked]
        for (i0, x0, y0), (i1, x1, y1) in zip(pts, pts[1:]):
            if i1 - i0 <= 6: cv2.line(im, (int(x0), int(y0)), (int(x1), int(y1)), AMBER, 3, cv2.LINE_AA)
        # bounces: camera + map
        for bf, x, y in missed:
            if 0 <= f - bf < SHOW:
                cv2.circle(im, (int(x), int(y)), 16, WHITE, 3, cv2.LINE_AA)
                cv2.circle(mp_, to_map(*project(H, x, y)), 10, WHITE, 3, cv2.LINE_AA)
        for c, real in picks.items():
            if 0 <= f - c < SHOW:
                col = GREEN if real else RED; x, y = cands[c]
                cv2.circle(im, (int(x), int(y)), 14, col, 3, cv2.LINE_AA)
                cv2.circle(mp_, to_map(*project(H, x, y)), 10, col, -1, cv2.LINE_AA)
        cv2.putText(mp_, f"{(off + f) / 30 // 60:.0f}:{(off + f) / 30 % 60:04.1f}", (14, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, WHITE, 2, cv2.LINE_AA)
        p.stdin.write(np.hstack([im, mp_]).tobytes())
    cap.release(); p.stdin.close(); p.wait()


if __name__ == "__main__":
    main(sys.argv[1], *map(int, sys.argv[2:4]))
