"""Top-K heatmap blobs per frame, otherwise IDENTICAL to scripts/pod_infer.py (PIC-226, Test B).

Same weights, same court mask, same 0.5 threshold, same 3-frame trios (windows
start on a multiple of 3 so the trio grouping equals a whole-video run), same
blob confidence. The only change: write up to K blobs per frame instead of the
single most confident one. Output CSV: Frame,Rank,X,Y,W,H,Conf (frames with no
blob write no row). Frame numbers are GLOBAL (as in a whole-video run).

Run under the TF 2.15 environment:
  /mnt/fast_scratch/tf215_env/venv/bin/python scripts/infer_topk.py \
      --video V --calib C --model /mnt/fast_scratch/tracknet_weights/weights_k14_epoch19 \
      --windows 100:130,400:430 --output out.csv
"""
import argparse, csv, os, sys, time
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np
import json
import pod_infer as P          # reuse court_mask, prep3, custom_loss, HEIGHT, WIDTH unchanged
import tensorflow as tf

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--calib", required=True)
    ap.add_argument("--model", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--windows", required=True, help="comma list of start:end seconds")
    ap.add_argument("--k", type=int, default=3); ap.add_argument("--thresh", type=float, default=0.5); ap.add_argument("--margin", type=float, default=80.0)
    a = ap.parse_args()
    calib = json.load(open(a.calib))
    model = tf.keras.models.load_model(a.model, custom_objects={"custom_loss": P.custom_loss}, compile=False)
    @tf.function
    def infer(x): return model(x, training=False)
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS); n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, f0 = cap.read(); assert ok
    cal_res = calib.get("calibration_resolution")
    out_w, out_h = cal_res if cal_res else (f0.shape[1], f0.shape[0])
    xr, yr = out_w / P.WIDTH, out_h / P.HEIGHT
    mask = P.court_mask(calib, f0.shape, a.margin)
    wins = []
    for w in a.windows.split(","):
        s, e = [float(v) for v in w.split(":")]
        s_f = max(0, (int(s * fps) // 3) * 3); e_f = min(n_frames, int(e * fps))
        if wins and s_f <= wins[-1][1]:
            wins[-1] = (wins[-1][0], max(wins[-1][1], e_f))
        else:
            wins.append((s_f, e_f))
    t0 = time.time(); done = 0
    with open(a.output, "w", newline="") as fh:
        wr = csv.writer(fh); wr.writerow(["Frame", "Rank", "X", "Y", "W", "H", "Conf"])
        for (s_f, e_f) in wins:
            cap.set(cv2.CAP_PROP_POS_FRAMES, s_f)
            count = s_f
            while count + 3 <= e_f:
                trio = []
                for _ in range(3):
                    ok, im = cap.read()
                    if not ok: break
                    trio.append(im * mask[:, :, None])
                if len(trio) < 3: break
                raw = infer(tf.constant(P.prep3(trio))).numpy()
                hp = ((raw[0] > a.thresh).astype(np.float32) * 255).astype(np.uint8); probs = raw[0]
                for i in range(3):
                    if np.amax(hp[i]) > 0:
                        cnts, _ = cv2.findContours(hp[i].copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        def conf(c, i=i):
                            m = np.zeros_like(hp[i]); cv2.drawContours(m, [c], -1, 1, thickness=-1)
                            return float(probs[i][m.astype(bool)].max())
                        ranked = sorted(cnts, key=conf, reverse=True)[:a.k]
                        for r, c in enumerate(ranked, 1):
                            b = cv2.boundingRect(c)
                            wr.writerow([count, r, int(xr * (b[0] + b[2] / 2)), int(yr * (b[1] + b[3] / 2)),
                                         round(xr * b[2], 1), round(yr * b[3], 1), round(conf(c), 4)])
                    count += 1
                done += 3
            fh.flush()
    print(f"{a.video}: {done} frames in {(time.time()-t0):.0f}s ({done/max(1e-9,time.time()-t0):.0f} fps) -> {a.output}")

if __name__ == "__main__":
    main()
