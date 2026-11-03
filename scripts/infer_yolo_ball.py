"""Modern YOLO (yolo11x, zero-shot 'sports ball') as a ball detector arm (PIC-226).

The 2026-08 comparison that retired YOLO (ADR-046) used a zero-shot yolov8x and one
rally window. This arm gives a current YOLO a fair run through the same downstream
pipeline on the same labelled excerpts as the TrackNet arms.

Rule, fixed before running: first 600 s, every frame; court mask applied first (the
same mask pod_infer.py uses); yolo11x.pt, imgsz 1280, conf >= 0.10, class 32 'sports
ball'; the highest-confidence box per frame; coordinates in calibration resolution;
CSV in the pod_infer format so everything downstream is unchanged.
Run with the repo venv: .venv/bin/python scripts/infer_yolo_ball.py --video V --calib C --output O
"""
import argparse, ast, csv, json, sys, time
import cv2
import numpy as np


def load_court_mask():
    src = open("scripts/pod_infer.py").read()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "court_mask")
    ns = {"np": np, "cv2": cv2}
    exec(ast.get_source_segment(src, fn), ns)
    return ns["court_mask"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--calib", required=True)
    ap.add_argument("--output", required=True); ap.add_argument("--weights", default="yolo11x.pt")
    ap.add_argument("--seconds", type=float, default=600.0); ap.add_argument("--imgsz", type=int, default=1280)
    a = ap.parse_args()
    from ultralytics import YOLO
    model = YOLO(a.weights)
    calib = json.load(open(a.calib))
    court_mask = load_court_mask()
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_max = int(a.seconds * fps)
    ok, f0 = cap.read()
    fh, fw = f0.shape[:2]
    cal_w, cal_h = calib.get("calibration_resolution") or [fw, fh]
    kx, ky = cal_w / fw, cal_h / fh
    mask = court_mask(calib, f0.shape, 80.0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    count, t0 = 0, time.time()
    with open(a.output, "w", newline="") as fo:
        wr = csv.writer(fo); wr.writerow(["Frame", "Visibility", "X", "Y", "W", "H", "Conf"])
        while count < n_max:
            batch = []
            for _ in range(8):
                ok, im = cap.read()
                if not ok or count + len(batch) >= n_max: break
                batch.append(im * mask[:, :, None])
            if not batch: break
            for res in model.predict(batch, imgsz=a.imgsz, conf=0.10, classes=[32], verbose=False):
                if res.boxes is None or len(res.boxes) == 0:
                    wr.writerow([count, 0, -1, -1, -1, -1, 0.0])
                else:
                    i = int(res.boxes.conf.argmax())
                    x0, y0, x1, y1 = res.boxes.xyxy[i].cpu().numpy()
                    wr.writerow([count, 1, int((x0 + x1) / 2 * kx), int((y0 + y1) / 2 * ky),
                                 round((x1 - x0) * kx, 1), round((y1 - y0) * ky, 1), round(float(res.boxes.conf[i]), 4)])
                count += 1
            if count % 1800 < 8:
                print(f"  {count}/{n_max}  {count / (time.time() - t0):.0f} fps", flush=True)
    print(f"done: {count} frames in {(time.time() - t0) / 60:.1f} min -> {a.output}", flush=True)


if __name__ == "__main__":
    main()
