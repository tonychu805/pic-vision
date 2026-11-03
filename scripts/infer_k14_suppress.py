"""k14 TrackNet with static bright-blob suppression as preprocessing (PIC-226 scenery test).

Question (operator, 2026-10-13): PGC footage has fixed light dots and reflections; the
brickwall footage does not. Can the picture be cleaned before the model sees it?

Preprocessing, fixed before running (no library required; NPP/CV-CUDA could run it faster):
 1. Background = per-pixel temporal median of 120 frames sampled evenly across the video.
 2. Bright small structures = white top-hat of that background (background minus its
    morphological opening with a 31 x 31 ellipse), thresholded at 30 grey levels.
 3. Keep connected components of 12-1500 px area whose bounding box is not elongated
    (long side <= 3 x short side), so court lines and the net are not touched; dilate by 3 px.
 4. In every frame, inpaint those pixels (cv2.inpaint, Telea, radius 3), then apply the court
    mask, resize and infer exactly as scripts/pod_infer.py.
--suppress 0 runs the same code path without step 4 (the control, so run-to-run noise and
the code path are shared). A debug image with the mask over a frame is written next to the
output. Run in the TF env.
"""
import argparse, csv, json, os, sys, time
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
sys.path.insert(0, "scripts")
import cv2
import numpy as np
import pod_infer as P


def static_bright_mask(cap, n_frames, k=120):
    idx = np.linspace(0, max(0, n_frames - 1), k).astype(int)
    stack = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, im = cap.read()
        if ok:
            stack.append(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY))
    bg = np.median(np.stack(stack), axis=0).astype(np.uint8)
    opened = cv2.morphologyEx(bg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    top = cv2.subtract(bg, opened)
    cand = (top >= 30).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    mask = np.zeros_like(cand)
    for c in range(1, n):
        x, y, w, h, a = stats[c]
        if 12 <= a <= 1500 and max(w, h) <= 3 * max(1, min(w, h)):
            mask[lab == c] = 1
    mask = cv2.dilate(mask, np.ones((7, 7), np.uint8))
    return mask, bg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--calib", required=True)
    ap.add_argument("--model", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--suppress", type=int, default=0)
    a = ap.parse_args()
    import tensorflow as tf
    calib = json.load(open(a.calib))
    model = tf.keras.models.load_model(a.model, custom_objects={"custom_loss": P.custom_loss}, compile=False)
    infer = tf.function(lambda x: model(x, training=False))
    cap = cv2.VideoCapture(a.video)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, f0 = cap.read()
    fh, fw = f0.shape[:2]
    cal_w, cal_h = calib.get("calibration_resolution") or [fw, fh]
    xr, yr = cal_w / P.WIDTH, cal_h / P.HEIGHT
    cmask = P.court_mask(calib, f0.shape, 80.0)
    smask = None
    if a.suppress:
        smask, bg = static_bright_mask(cap, n_frames)
        inside = int((smask & cmask).sum())
        print(f"suppression mask: {int(smask.sum())} px total, {inside} px inside the court area "
              f"({100 * inside / max(1, int(cmask.sum())):.3f}% of it)", flush=True)
        dbg = cv2.cvtColor(bg, cv2.COLOR_GRAY2BGR)
        dbg[smask > 0] = (0, 0, 255)
        cv2.imwrite(a.output.replace(".csv", "_mask.png"), dbg)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    n_sel = n_frames // 3 * 3
    count, t0 = 0, time.time()
    with open(a.output, "w", newline="") as fo:
        wr = csv.writer(fo); wr.writerow(["Frame", "Visibility", "X", "Y", "W", "H", "Conf"])
        while count < n_sel:
            imgs = []
            for _ in range(3):
                ok, im = cap.read()
                if not ok: break
                if smask is not None:
                    im = cv2.inpaint(im, smask, 3, cv2.INPAINT_TELEA)
                imgs.append(im * cmask[:, :, None])
            if len(imgs) < 3: break
            chans = []
            for im in imgs:
                r = cv2.resize(im, (P.WIDTH, P.HEIGHT))[..., ::-1].astype(np.float32) / 255.0
                chans.extend([r[..., 0], r[..., 1], r[..., 2]])
            x = np.stack(chans).reshape(1, 9, P.HEIGHT, P.WIDTH).astype(np.float32)
            raw = infer(tf.constant(x)).numpy()
            hp = ((raw[0] > 0.5).astype(np.uint8) * 255)
            for i in range(3):
                if hp[i].max() <= 0:
                    wr.writerow([count, 0, -1, -1, -1, -1, 0.0])
                else:
                    cnts, _ = cv2.findContours(hp[i].copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    def conf(c, i=i):
                        m = np.zeros_like(hp[i]); cv2.drawContours(m, [c], -1, 1, thickness=-1)
                        return float(raw[0][i][m.astype(bool)].max())
                    best = max(cnts, key=conf); b = cv2.boundingRect(best)
                    wr.writerow([count, 1, int(xr * (b[0] + b[2] / 2)), int(yr * (b[1] + b[3] / 2)),
                                 round(xr * b[2], 1), round(yr * b[3], 1), round(conf(best), 4)])
                count += 1
            if count % 3000 == 0:
                print(f"  {count}/{n_sel}  {count / (time.time() - t0):.0f} fps", flush=True)
    print(f"done: {count} frames in {(time.time() - t0) / 60:.1f} min -> {a.output}", flush=True)


if __name__ == "__main__":
    main()
