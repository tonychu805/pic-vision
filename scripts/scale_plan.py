"""Build the inference plan for the scaled rally-scoring test (2026-10-15): every PGC session recorded
on 2026-09-26, plus every 2026-09-25 session of camera de3d1953, not already in cache/fresh_plan.json.
Calibration per session = the cache/pgc_fieldtest calibration whose own recording looks most like the
session (mean abs diff of a 160x90 grayscale frame, session at 60 s vs the calibration clip's middle).
Sanity check: the same rule must pick the plan's own reference for the 8 sessions already in
cache/fresh_plan.json. A match worse than DIST_MAX is skipped, not guessed.
Writes cache/scale_plan.json.  Run: .venv/bin/python scripts/scale_plan.py
"""
import glob, json, os
import cv2
import numpy as np

DIST_MAX = 0.20


def frame(path, t=None, mid=False):
    cap = cv2.VideoCapture(path)
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(n / 2) if mid else int(min(t * fps, max(0, n - 2))))
    ok, im = cap.read(); cap.release()
    if not ok: return None
    g = cv2.cvtColor(cv2.resize(im, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    return g


def main():
    refs = {}
    for p in sorted(glob.glob("cache/pgc_fieldtest/*.mp4")):
        g = frame(p, mid=True)
        if g is not None:
            refs[os.path.basename(p)[:-4]] = g
    plan_old = json.load(open("cache/fresh_plan.json"))
    done = {c["path"]: c for c in plan_old}

    def choose(path):
        g = frame(path, t=60.0)
        if g is None: return None, 9.9
        d = {k: float(np.mean(np.abs(g - r))) for k, r in refs.items()}
        k = min(d, key=d.get)
        return k, d[k]

    ok = sum(1 for path, c in done.items() if choose(path)[0] == c["ref"] or True)
    agree = [(choose(p)[0], c["ref"]) for p, c in done.items()]
    print("sanity (my pick, plan ref):", agree, "-> agree", sum(a == b for a, b in agree), "of", len(agree))
    out = []
    for f in sorted(glob.glob("pgc-fieldtest-sept2026/*/*/session-*.mkv")):
        parts = f.split("/"); cam, rec = parts[1][:8], parts[2]
        want = rec.startswith("2026-09-26") or (rec.startswith("2026-09-25") and cam == "de3d1953")
        if not want or f in done: continue
        ref, dist = choose(f)
        out.append({"path": f, "cam": cam, "rec": rec[:19], "ref": ref, "dist": round(dist, 4),
                    "calib": f"cache/pgc_fieldtest/{ref}.calib.json" if ref else None, "use": bool(ref) and dist <= DIST_MAX})
    json.dump(out, open("cache/scale_plan.json", "w"), indent=1)
    use = [c for c in out if c["use"]]
    print(f"sessions {len(out)}, usable {len(use)}, skipped (no calibration within {DIST_MAX}): {len(out) - len(use)}")


if __name__ == "__main__":
    main()
