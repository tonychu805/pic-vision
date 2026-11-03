"""Can Gemini find the rallies in a video by itself? Head-to-head on brickwall (PIC-226).

Operator question (2026-10-13): would going straight to Gemini, with the right
system prompt, replace TrackNet + RunPod for finding rallies? Nothing has been
measured on our footage: the 2026-08-16 verifier (archive/verify.py, ADR-085) was
never scored and its verdicts changed with the encoding alone.

Excerpts (both are the first 900 s; labels with end > 900 s are excluded):
  brickwall_30fps  videos/brickwall_30fps.mp4       eval/labels/brickwall_30fps.jsonl
  brickwall-SEMI   videos/brickwall_semi_30fps.mp4  eval/labels/brickwall-SEMI.jsonl
Public YouTube footage of a tournament stream, fully hand-labelled (LABELING v5
rules; start is a lead-in 0-3 s before serve contact, end is the ball going dead).

Conditions per excerpt (3 calls each, temperature 0, same prompt):
  A  original encode, 1 fps (the API default)
  B  re-encoded (libx264 crf 30), 1 fps  -> consistency against A (ADR-085's failure)
  C  original encode, 5 fps              -> does a higher sampling rate matter?

Scoring: greedy one-to-one match at IoU >= 0.5 (eval.harness.match_intervals,
TECH_SPEC section 11), against the shipped pipeline (base.detect: TrackNet k14,
gap_sec 3.0, min_crossings 6) on the SAME excerpts.

BAR, written before any Gemini call:
 1. REPLACEMENT passes only if all three hold, pooled over both excerpts, for
    condition A: precision >= the pipeline's precision; recall >= the pipeline's
    recall - 0.05; AND agreement(A, B) >= 0.85 where agreement = 2 * matched /
    (n_A + n_B) at IoU >= 0.5.
 2. VETO (Gemini filters the pipeline's candidates; a candidate is kept if some
    Gemini interval overlaps it at IoU >= 0.5) passes if it removes >= 50% of the
    pipeline's false positives while losing <= 10% of its true positives, pooled,
    condition A.
 Condition C is reported, not gated. Two excerpts, one tournament stream, in
 sample: a pass is a lead worth a fresh venue test, not a ship decision.
 The prompt below is frozen before the first call; it is not tuned on results.

Run:
  GOOGLE_API_KEY must be in the environment or .env (never printed).
  .venv/bin/python scripts/gemini_head_to_head.py --dry-run          # no API, tests scoring
  .venv/bin/python scripts/gemini_head_to_head.py --list-models
  .venv/bin/python scripts/gemini_head_to_head.py --run --model <id>
"""
import argparse, json, os, subprocess, sys, time
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from eval.harness import match_intervals, load_labels
import validate_absolute_ranking as base

WINDOW = 900.0
OUT = "cache/gemini"
EXCERPTS = [
    {"name": "brickwall_30fps", "video": "videos/brickwall_30fps.mp4", "labels": "eval/labels/brickwall_30fps.jsonl",
     "csv": "cache/brickwall_30fps_predictions_k14.csv", "calib": "calib/brickwall_30fps_calib.json"},
    {"name": "brickwall-SEMI", "video": "videos/brickwall_semi_30fps.mp4", "labels": "eval/labels/brickwall-SEMI.jsonl",
     "csv": "cache/brickwall_semi_predictions_k14.csv", "calib": "calib/brickwall_semi_calib.json"},
]
CONDITIONS = [("A", "original", 1), ("B", "reencoded", 1), ("C", "original", 5)]

SYSTEM = """You are annotating a fixed-camera pickleball video. Find every RALLY.

A rally starts at the serve and ends when the ball becomes dead (it touches the
ground a second time, goes out, hits the net and stays, or a fault is made).
Count it as a rally ONLY if the ball is hit back and forth live, with at least 3
paddle contacts (serve, return and at least one more).
Do NOT include: a served ball that is a fault (net not in, wrong box, kitchen,
out) with no return; a serve with only the return and no third contact;
courtesy returns or taps back to the server after the point; picking up balls,
tossing a ball in, feeding, ball-machine or drill hitting, warm-up hitting, or
time between points.
A serve that touches the net and lands in the correct box is live and counts.

Report start as about 1 to 3 seconds before the serve contact, and end as the
moment the ball goes dead. Times are seconds from the start of the video, as
numbers with one decimal. List rallies in time order and do not overlap them.
Return only JSON: {"rallies": [{"start": <seconds>, "end": <seconds>}]}"""


def load_env_key():
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key and os.path.exists(".env"):
        for line in open(".env"):
            if line.startswith(("GOOGLE_API_KEY=", "GEMINI_API_KEY=")):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key


def truth_and_pipeline(ex):
    labels = [r for r in load_labels(ex["labels"]) if r["end"] <= WINDOW]
    calib = json.load(open(ex["calib"]))
    segs = [s for s in base.detect(ex["csv"], calib)[0] if s["end"] <= WINDOW]
    return labels, [{"start": s["start"], "end": s["end"]} for s in segs]


def reencode(src, dst):
    if os.path.exists(dst):
        return dst
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-t", str(WINDOW), "-an", "-c:v", "libx264",
                    "-crf", "30", "-preset", "veryfast", "-pix_fmt", "yuv420p", dst], check=True)
    return dst


def ask_gemini(client, types, model, path, fps, tag):
    cache = f"{OUT}/{tag}.json"
    if os.path.exists(cache):
        return json.load(open(cache))
    f = client.files.upload(file=path)
    while f.state and f.state.name == "PROCESSING":
        time.sleep(3); f = client.files.get(name=f.name)
    if f.state and f.state.name != "ACTIVE":
        raise RuntimeError(f"upload failed: {f.state}")
    part = types.Part(file_data=types.FileData(file_uri=f.uri, mime_type=f.mime_type or "video/mp4"),
                      video_metadata=types.VideoMetadata(fps=fps, start_offset="0s", end_offset=f"{int(WINDOW)}s"))
    resp = client.models.generate_content(
        model=model, contents=[part, "Find every rally in this video."],
        config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.0,
                                           response_mime_type="application/json"))
    u = resp.usage_metadata
    rec = {"model": model, "fps": fps, "text": resp.text,
           "tokens": {"prompt": getattr(u, "prompt_token_count", None), "output": getattr(u, "candidates_token_count", None)}}
    json.dump(rec, open(cache, "w"), indent=1)
    try:
        client.files.delete(name=f.name)
    except Exception:
        pass
    return rec


def parse(rec):
    try:
        items = json.loads(rec["text"])["rallies"]
        out = sorted(({"start": float(r["start"]), "end": float(r["end"])} for r in items if r["end"] > r["start"]),
                     key=lambda r: r["start"])
        return out, True
    except Exception:
        return [], False


def pr(preds, gts):
    m = match_intervals(preds, gts)
    tp = len(m["matches"])
    return tp, len(preds), len(gts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-models", action="store_true"); ap.add_argument("--model")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    data = {ex["name"]: truth_and_pipeline(ex) for ex in EXCERPTS}
    print(f"{'excerpt':16s} {'labels':>7s} {'pipeline segs':>14s}")
    for n, (lab, pipe) in data.items():
        print(f"{n:16s} {len(lab):7d} {len(pipe):14d}")
    results = {}      # (name, cond) -> predicted intervals
    if a.dry_run:
        for n, (lab, pipe) in data.items():
            for c, _, _ in CONDITIONS:
                results[(n, c)] = pipe if c != "B" else pipe[:]
    elif a.list_models or a.run:
        key = load_env_key()
        if not key:
            sys.exit("No GOOGLE_API_KEY / GEMINI_API_KEY in the environment or .env.")
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        if a.list_models:
            for m in client.models.list():
                if "generateContent" in (getattr(m, "supported_actions", None) or []):
                    print(m.name)
            return
        if not a.model:
            sys.exit("--model is required (see --list-models).")
        print(f"\nplanned calls: {len(EXCERPTS) * len(CONDITIONS)}; about {int(WINDOW)} s of video each; "
              f"input about {int(WINDOW) * 100:,} tokens at 1 fps, about {int(WINDOW) * 500:,} at 5 fps (doc figure, 100 tokens/s at 1 fps)")
        for ex in EXCERPTS:
            for c, enc, fps in CONDITIONS:
                path = ex["video"] if enc == "original" else reencode(ex["video"], f"{OUT}/{ex['name']}_crf30.mp4")
                rec = ask_gemini(client, types, a.model, path, fps, f"{ex['name']}_{c}")
                preds, ok = parse(rec)
                results[(ex["name"], c)] = preds
                print(f"  {ex['name']} {c}: {len(preds)} rallies parsed={'yes' if ok else 'NO'} tokens={rec['tokens']}")
    else:
        sys.exit("Nothing to do: pass --dry-run, --list-models or --run.")

    print("\n=== precision / recall at IoU >= 0.5 (pooled over both excerpts)")
    def pooled(get):
        tp = n = g = 0
        for name, (lab, pipe) in data.items():
            t, p_, g_ = pr(get(name), lab); tp += t; n += p_; g += g_
        return tp, n, g
    base_tp, base_n, base_g = pooled(lambda nm: data[nm][1])
    p0, r0 = base_tp / max(base_n, 1), base_tp / max(base_g, 1)
    print(f"{'pipeline':14s} precision {p0:5.1%} ({base_tp}/{base_n})   recall {r0:5.1%} ({base_tp}/{base_g})")
    for c, enc, fps in CONDITIONS:
        tp, n, g = pooled(lambda nm: results[(nm, c)])
        print(f"{'gemini ' + c + ' ' + str(fps) + 'fps':14s} precision {tp / max(n, 1):5.1%} ({tp}/{n})   recall {tp / max(g, 1):5.1%} ({tp}/{g})")
        for name, (lab, pipe) in data.items():
            t, p_, g_ = pr(results[(name, c)], lab)
            print(f"{'':14s}   {name:16s} P {t / max(p_, 1):5.1%}  R {t / max(g_, 1):5.1%}  (pred {p_}, labels {g_})")

    print("\n=== consistency A vs B (same prompt, different encode)")
    m_tot = nA = nB = 0
    for name in data:
        m = len(match_intervals(results[(name, "A")], results[(name, "B")])["matches"])
        m_tot += m; nA += len(results[(name, "A")]); nB += len(results[(name, "B")])
    agree = 2 * m_tot / max(nA + nB, 1)
    print(f"agreement {agree:.2f}  (matched {m_tot}; A {nA}, B {nB})")

    print("\n=== veto: Gemini A as a filter on the pipeline's candidates")
    kept_tp = lost_tp = removed_fp = kept_fp = 0
    for name, (lab, pipe) in data.items():
        m = match_intervals(pipe, lab); true_idx = {pi for pi, _, _ in m["matches"]}
        for i, s in enumerate(pipe):
            keep = any(match_intervals([s], [g])["matches"] for g in results[(name, "A")])
            if i in true_idx:
                kept_tp += keep; lost_tp += (not keep)
            else:
                removed_fp += (not keep); kept_fp += keep
    tpn, fpn = kept_tp + lost_tp, removed_fp + kept_fp
    print(f"removes {removed_fp}/{fpn} of the pipeline's false positives ({removed_fp / max(fpn, 1):.0%}); "
          f"loses {lost_tp}/{tpn} of its true positives ({lost_tp / max(tpn, 1):.0%})")

    tpA, nA_, gA = pooled(lambda nm: results[(nm, "A")])
    pA, rA = tpA / max(nA_, 1), tpA / max(gA, 1)
    rep = pA >= p0 and rA >= r0 - 0.05 and agree >= 0.85
    veto = removed_fp / max(fpn, 1) >= 0.5 and lost_tp / max(tpn, 1) <= 0.10
    print(f"\nREPLACEMENT bar: {'PASS' if rep else 'FAIL'}   VETO bar: {'PASS' if veto else 'FAIL'}"
          + ("   (dry run: pipeline stands in for Gemini, numbers are not a result)" if a.dry_run else ""))


if __name__ == "__main__":
    main()
