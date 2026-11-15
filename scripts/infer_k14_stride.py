"""k14 TrackNet on a video with an optional frame stride (PIC-226 frame-rate test).

stride 1 = every frame (native rate); stride 2 = every second frame (a 60 fps source
becomes exactly 30 fps from the same encode). Same weights, court mask and blob picking
as scripts/pod_infer.py. Output Frame = index in the SELECTED sequence; coordinates in
source pixels (calibration resolution, or the frame size when the calibration has none).
Run in the TF env, as scripts/infer_crop_k14.py.
"""
import argparse, csv, json, os, sys, time
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
sys.path.insert(0, "scripts")
import cv2
import numpy as np
import pod_infer as P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--calib", required=True)
    ap.add_argument("--model", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--seconds", type=float, default=900.0); ap.add_argument("--stride", type=int, default=1)
    a = ap.parse_args()
    import tensorflow as tf
    calib = json.load(open(a.calib))
    model = tf.keras.models.load_model(a.model, custom_objects={"custom_loss": P.custom_loss}, compile=False)
    infer = tf.function(lambda x: model(x, training=False))
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    eff = fps / a.stride
    n_sel = int(a.seconds * eff) // 3 * 3
    ok, f0 = cap.read()
    fh, fw = f0.shape[:2]
    cal_w, cal_h = calib.get("calibration_resolution") or [fw, fh]
    xr, yr = cal_w / P.WIDTH, cal_h / P.HEIGHT
    mask = P.court_mask(calib, f0.shape, 80.0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    print(f"{fw}x{fh} source {fps:.2f} fps, stride {a.stride} -> {eff:.2f} fps, {n_sel} frames", flush=True)
    src_i, count, t0 = 0, 0, time.time()

    def next_selected():
        nonlocal src_i
        ok = True
        for _ in range(a.stride):
            ok, im = cap.read()
            src_i += 1
            if not ok: return None
        return im

    with open(a.output, "w", newline="") as fo:
        wr = csv.writer(fo); wr.writerow(["Frame", "Visibility", "X", "Y", "W", "H", "Conf"])
        # stride 1: frames 0,1,2,...; stride 2: frames 1,3,5,... (the first read of each group is the one kept)
        while count < n_sel:
            imgs = []
            for _ in range(3):
                im = next_selected()
                if im is None: break
                imgs.append(im * mask[:, :, None])
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
