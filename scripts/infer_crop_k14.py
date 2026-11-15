"""k14 TrackNet on a court crop instead of the whole frame (PIC-226 zoom test).

Same weights, same court mask, same blob picking as scripts/pod_infer.py; the only
change is that each frame is cropped to a 16:9 box around the court (plus airspace)
before the 512 x 288 resize, so the ball covers more of the network's input.
Coordinates are mapped back to full-frame pixels, so every downstream consumer is
unchanged. Experiment only; not wired into the pipeline.

Crop rule, fixed before running: bounding box of the four court corners through the
inverse homography; left/right +10% of its width, top -25% of its height (airspace
for the ball in flight), bottom +5%; then widened or heightened symmetrically to
16:9, clamped to the frame.
Run in the TF env (see scripts/run_fresh_inference.py for LD_LIBRARY_PATH):
  python scripts/infer_crop_k14.py --video V --calib C --model W --output O --seconds 600
"""
import argparse, csv, json, os, sys, time
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
sys.path.insert(0, "scripts")
import cv2
import numpy as np
import pod_infer as P          # reuses custom_loss, court_mask, HEIGHT, WIDTH


def crop_box(calib, fw, fh):
    Hinv = np.linalg.inv(np.array(calib["homography"], dtype=np.float64))
    w_ft, l_ft = calib.get("court_size_ft", [20.0, 44.0])
    pts = cv2.perspectiveTransform(np.array([[[0, 0], [w_ft, 0], [0, l_ft], [w_ft, l_ft]]], dtype=np.float32), Hinv)[0]
    x0, x1, y0, y1 = pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()
    bw, bh = x1 - x0, y1 - y0
    x0, x1 = x0 - 0.10 * bw, x1 + 0.10 * bw
    y0, y1 = y0 - 0.25 * bh, y1 + 0.05 * bh
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = x1 - x0, y1 - y0
    if w / h < 16 / 9: w = h * 16 / 9
    else: h = w * 9 / 16
    w, h = min(w, fw), min(h, fh)
    x0 = min(max(0, cx - w / 2), fw - w); y0 = min(max(0, cy - h / 2), fh - h)
    return int(x0), int(y0), int(w), int(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--calib", required=True)
    ap.add_argument("--model", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--seconds", type=float, default=600.0)
    a = ap.parse_args()
    import tensorflow as tf
    calib = json.load(open(a.calib))
    model = tf.keras.models.load_model(a.model, custom_objects={"custom_loss": P.custom_loss}, compile=False)
    infer = tf.function(lambda x: model(x, training=False))
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_max = int(a.seconds * fps) // 3 * 3
    ok, f0 = cap.read()
    fh, fw = f0.shape[:2]
    cal_res = calib.get("calibration_resolution") or [fw, fh]
    mask = P.court_mask(calib, f0.shape, 80.0)
    cx0, cy0, cw, ch = crop_box(calib, fw, fh)
    print(f"frame {fw}x{fh}, crop x={cx0} y={cy0} w={cw} h={ch} ({100 * cw / fw:.0f}% of the width)", flush=True)
    sx = cw / P.WIDTH * (cal_res[0] / fw); sy = ch / P.HEIGHT * (cal_res[1] / fh)
    ox, oy = cx0 * cal_res[0] / fw, cy0 * cal_res[1] / fh
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    count, t0 = 0, time.time()
    with open(a.output, "w", newline="") as fh_:
        wr = csv.writer(fh_); wr.writerow(["Frame", "Visibility", "X", "Y", "W", "H", "Conf"])
        while count < n_max:
            imgs = []
            for _ in range(3):
                ok, im = cap.read()
                if not ok: break
                imgs.append(im * mask[:, :, None])
            if len(imgs) < 3: break
            chans = []
            for im in imgs:
                r = cv2.resize(im[cy0:cy0 + ch, cx0:cx0 + cw], (P.WIDTH, P.HEIGHT))[..., ::-1].astype(np.float32) / 255.0
                chans.extend([r[..., 0], r[..., 1], r[..., 2]])
            x = np.stack(chans).reshape(1, 9, P.HEIGHT, P.WIDTH).astype(np.float32)
            raw = infer(tf.constant(x)).numpy()
            hp = ((raw[0] > 0.5).astype(np.float32) * 255).astype(np.uint8)
            for i in range(3):
                if np.amax(hp[i]) <= 0:
                    wr.writerow([count, 0, -1, -1, -1, -1, 0.0])
                else:
                    cnts, _ = cv2.findContours(hp[i].copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    def conf(c, i=i):
                        m = np.zeros_like(hp[i]); cv2.drawContours(m, [c], -1, 1, thickness=-1)
                        return float(raw[0][i][m.astype(bool)].max())
                    best = max(cnts, key=conf); b = cv2.boundingRect(best)
                    wr.writerow([count, 1, int(ox + sx * (b[0] + b[2] / 2)), int(oy + sy * (b[1] + b[3] / 2)),
                                 round(sx * b[2], 1), round(sy * b[3], 1), round(conf(best), 4)])
                count += 1
            if count % 1800 == 0:
                print(f"  {count}/{n_max}  {count / (time.time() - t0):.0f} fps", flush=True)
    print(f"done: {count} frames in {(time.time() - t0) / 60:.1f} min -> {a.output}", flush=True)


if __name__ == "__main__":
    main()
