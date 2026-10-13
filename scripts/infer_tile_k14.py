"""k14 TrackNet on two overlapping tiles instead of the whole frame (PIC-226 zoom test).

The first registered arm (scripts/infer_crop_k14.py, crop to the court) turned out to
be a no-op on the test footage: the court corners span 82-85% of the frame width on
pb_draft_cup and brickwall-SEMI, so a 16:9 crop around the court is 99% of the width
(zoom 1.0x). It was stopped and not scored. This arm splits the court band into two
tiles so the ball gets more of the network's 512 x 288 input.

Tile rule, fixed before running: two tiles of 60% of the frame width each
(x = 0..0.60W and 0.40W..W, a 20% overlap), 16:9, vertically placed over the court
band plus airspace (court corners' y span, top - 25% of it, bottom + 5%, centred).
Each tile is resized to 512 x 288 (scale about 0.44 vs 0.27 for the whole frame, so
the ball is about 1.7x larger). The court mask is applied first. Per frame the
highest-confidence blob across the two tiles is kept; coordinates are mapped back to
full-frame pixels (calibration resolution). Same weights, same blob picking.
Run in the TF env, as infer_crop_k14.py.
"""
import argparse, csv, json, os, sys, time
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
sys.path.insert(0, "scripts")
import cv2
import numpy as np
import pod_infer as P


def tile_boxes(calib, fw, fh):
    Hinv = np.linalg.inv(np.array(calib["homography"], dtype=np.float64))
    w_ft, l_ft = calib.get("court_size_ft", [20.0, 44.0])
    pts = cv2.perspectiveTransform(np.array([[[0, 0], [w_ft, 0], [0, l_ft], [w_ft, l_ft]]], dtype=np.float32), Hinv)[0]
    y0, y1 = pts[:, 1].min(), pts[:, 1].max()
    bh = y1 - y0
    top, bot = y0 - 0.25 * bh, y1 + 0.05 * bh
    tw = int(0.60 * fw); th = int(tw * 9 / 16)
    cy = (top + bot) / 2
    ty = int(min(max(0, cy - th / 2), fh - th))
    return [(0, ty, tw, th), (fw - tw, ty, tw, th)]


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
    cal_w, cal_h = calib.get("calibration_resolution") or [fw, fh]
    mask = P.court_mask(calib, f0.shape, 80.0)
    boxes = tile_boxes(calib, fw, fh)
    print(f"frame {fw}x{fh}; tiles {boxes} ({100 * boxes[0][2] / fw:.0f}% width each)", flush=True)
    kx, ky = cal_w / fw, cal_h / fh
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
            batch = []
            for (bx, by, bw, bh) in boxes:
                chans = []
                for im in imgs:
                    r = cv2.resize(im[by:by + bh, bx:bx + bw], (P.WIDTH, P.HEIGHT))[..., ::-1].astype(np.float32) / 255.0
                    chans.extend([r[..., 0], r[..., 1], r[..., 2]])
                batch.append(np.stack(chans))
            raw = infer(tf.constant(np.stack(batch).astype(np.float32))).numpy()   # (tiles, 3, H, W)
            for i in range(3):
                best = None
                for ti, (bx, by, bw, bh) in enumerate(boxes):
                    hp = ((raw[ti][i] > 0.5).astype(np.uint8) * 255)
                    if hp.max() <= 0: continue
                    cnts, _ = cv2.findContours(hp.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for c in cnts:
                        m = np.zeros_like(hp); cv2.drawContours(m, [c], -1, 1, thickness=-1)
                        cf = float(raw[ti][i][m.astype(bool)].max())
                        if best is None or cf > best[0]:
                            b = cv2.boundingRect(c)
                            sx, sy = bw / P.WIDTH, bh / P.HEIGHT
                            best = (cf, kx * (bx + sx * (b[0] + b[2] / 2)), ky * (by + sy * (b[1] + b[3] / 2)),
                                    kx * sx * b[2], ky * sy * b[3])
                if best is None:
                    wr.writerow([count, 0, -1, -1, -1, -1, 0.0])
                else:
                    wr.writerow([count, 1, int(best[1]), int(best[2]), round(best[3], 1), round(best[4], 1), round(best[0], 4)])
                count += 1
            if count % 1800 == 0:
                print(f"  {count}/{n_max}  {count / (time.time() - t0):.0f} fps", flush=True)
    print(f"done: {count} frames in {(time.time() - t0) / 60:.1f} min -> {a.output}", flush=True)


if __name__ == "__main__":
    main()
