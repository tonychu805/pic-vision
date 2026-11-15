"""Can the recording's own audio tell a floor bounce from a paddle hit? (2026-10-15)

Context. The tile arm's candidates on the unselected PGC chunk (eda301d9 2026-09-25 08:21
session-000) are bounces or paddle hits; the ball track cannot tell them apart (EXPERIMENTS.md,
candidate review). The recording has a 16 kHz mono audio track. Impact sounds need no ball track.

Data. Operator tags from CVAT project 'tile-candidate-review': 6 bounce, 13 paddle_hit
(the 1 not_ball is excluded). The 17 'matched' candidates (project 'tile-matched-review') are
HELD OUT: not read by this script until --heldout is passed, after the operator has tagged them.

Measurement, fixed BEFORE the run. t = candidate frame / 30 s. Audio high-passed at 300 Hz;
envelope = RMS in 10 ms windows, 5 ms hop. R = max envelope in [t-0.15, t+0.15] divided by the
median envelope in [t-1.5, t+1.5]. The event 'has a sound' if R >= 4. At the envelope peak,
50 ms of audio gives: centroid (spectral centroid, Hz), hf (share of energy above 2 kHz),
R itself. AUC of each feature for bounce vs hit.

BAR.
  (a) sound present   >= 80% of the 19 events have R >= 4, AND the same rate for 200 random
                      times in the chunk is <= 40% (otherwise 'a sound' says nothing: the hall
                      is noisy)
  (b) separable       the feature with the largest |AUC - 0.5| has AUC >= 0.85 or <= 0.15
  (c) confirmed       on the 17 held-out candidates, once tagged: same direction, AUC >= 0.75
Passing (a)+(b) is a lead worth tagging for, not a result; (c) is the check. n = 6 vs 13 here,
so a pass on (b) alone is weak.
Run: .venv/bin/python scripts/eval_audio_hit_vs_bounce.py [--heldout]
"""
import json, subprocess, sys
import numpy as np

V = "pgc-fieldtest-sept2026/eda301d9-b093-478a-aec1-51a8e7a5c08c/2026-09-25T08-21-01-111Z/session-000.mkv"
SR = 16000


def audio():
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", V, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    # 300 Hz high-pass by FFT-free one-pole: y[n] = a (y[n-1] + x[n] - x[n-1])
    a = 1.0 / (1.0 + 2 * np.pi * 300.0 / SR)
    y = np.zeros_like(x); p = 0.0
    from scipy.signal import lfilter
    y = lfilter([a, -a], [1.0, -a], x)
    return y


def envelope(y):
    w, h = int(0.010 * SR), int(0.005 * SR)
    n = (len(y) - w) // h
    idx = np.arange(n)[:, None] * h + np.arange(w)[None, :]
    return np.sqrt((y[idx] ** 2).mean(axis=1)), h / SR


def features(y, env, step, t):
    lo, hi = int((t - 0.15) / step), int((t + 0.15) / step)
    if lo < 0 or hi >= len(env): return None
    base = np.median(env[max(0, int((t - 1.5) / step)):int((t + 1.5) / step)]) + 1e-9
    k = lo + int(np.argmax(env[lo:hi + 1]))
    R = env[k] / base
    c = int(k * step * SR); seg = y[c - int(0.025 * SR):c + int(0.025 * SR)]
    if len(seg) < 100: return None
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    fr = np.fft.rfftfreq(len(seg), 1 / SR)
    return {"R": float(R), "centroid": float((fr * sp).sum() / (sp.sum() + 1e-12)),
            "hf": float(sp[fr > 2000].sum() / (sp.sum() + 1e-12)), "offset_ms": float((k * step - t) * 1000)}


def auc(pos, neg):
    s = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return s / (len(pos) * len(neg))


def tags(project):
    q = f"""select t.name, l.name from engine_task t join engine_segment s on s.task_id=t.id join engine_job j on j.segment_id=s.id
            join engine_labeledimage i on i.job_id=j.id join engine_label l on l.id=i.label_id where t.project_id={project}"""
    out = subprocess.run(["docker", "--context", "desktop-linux", "exec", "cvat_db", "psql", "-U", "root", "-d", "cvat",
                          "-tA", "-F", "|", "-c", q], capture_output=True, text=True, check=True).stdout
    return {l.split("|")[0]: l.split("|")[1] for l in out.splitlines()}


def frame_of(name):
    return int(name.split("frame ")[1].split(" ")[0])


def main(heldout):
    y = audio(); env, step = envelope(y)
    print(f"audio {len(y) / SR:.1f} s")
    proj = 4 if heldout else 3
    ev = [(frame_of(n), lab) for n, lab in tags(proj).items() if lab in ("bounce", "paddle_hit")]
    rows = [(lab, features(y, env, step, f / 30)) for f, lab in ev]
    rows = [(l, f) for l, f in rows if f]
    nb = sum(1 for l, _ in rows if l == "bounce"); nh = len(rows) - nb
    print(f"events: {len(rows)} ({nb} bounce, {nh} paddle_hit)")
    present = np.mean([f["R"] >= 4 for _, f in rows])
    rng = np.random.default_rng(0)
    rand = [features(y, env, step, t) for t in rng.uniform(5, len(y) / SR - 5, 200)]
    rand_rate = np.mean([f["R"] >= 4 for f in rand if f])
    print(f"sound present (R>=4): events {present:.0%}   random times {rand_rate:.0%}")
    print(f"median |peak offset| from the candidate: {np.median([abs(f['offset_ms']) for _, f in rows]):.0f} ms")
    best = None
    for k in ("R", "centroid", "hf"):
        b = [f[k] for l, f in rows if l == "bounce"]; h = [f[k] for l, f in rows if l == "paddle_hit"]
        a = auc(b, h)
        print(f"  {k:9s} bounce median {np.median(b):9.3f}  hit median {np.median(h):9.3f}  AUC(bounce>hit) {a:.2f}")
        if best is None or abs(a - 0.5) > abs(best[1] - 0.5): best = (k, a)
    print(f"best feature: {best[0]} AUC {best[1]:.2f}")
    if not heldout:
        ok_a = present >= 0.8 and rand_rate <= 0.4; ok_b = best[1] >= 0.85 or best[1] <= 0.15
        print(f"(a) sound present: {'PASS' if ok_a else 'FAIL'}   (b) separable: {'PASS' if ok_b else 'FAIL'}")


if __name__ == "__main__":
    main("--heldout" in sys.argv)
