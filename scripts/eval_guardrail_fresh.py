"""Test L: a combined "real game?" guardrail on fresh, never-judged PGC rallies (2026-10-17, PIC-226).
Pre-registered: this file, the sample, both rules and the bar were committed before the operator judged any clip and
before any Jev call on them.

GUARDRAIL = flag a detected rally if EITHER
  (1) Jev (jev-1.14, same contact sheet and Noul question as Test K, scripts/eval_jev_rally.py) answers real < 0.4.
      0.4 was read off Test K's in-sample curve after its result (1 of 75 real, 13 of 37 not-real); this test is
      what makes it count.
  (2) the frozen pause rule (EXPERIMENTS.md 2026-10-12, apply_pause_rule_fresh.py): gap to the previous AND to the
      next detected rally both <= 6.0 s, within the same recording.
SAMPLE: the 36 D4-scale sessions (cache/scale/*.csv; none of their kept rallies has a verdict; the 12 D4-dropped
  rallies the operator reviewed are excluded). Production detection (validate_absolute_ranking.detect). Per session
  the top 2 rallies by the shipped score (score_segments), i.e. what a reel opens with; then a seed-20261017 random
  40 of that pool. Clips are silent, shuffled, numbered 401-440, judged blind on the same page as earlier samples
  (real / very short / not a rally / can't tell, plus a reason).
BAR (judged clips, "can't tell" excluded; "very short" reported, not gated):
  real flagged <= max(1, floor(5% of real))  AND  not-real flagged >= 50% of not-real.
  If fewer than 8 clips are judged not-real, the not-real half is reported as underpowered, not passed.
SAMPLE AS BUILT (before any verdict): pool 60, picked 40 from 25 recordings; camera de3d1953 (Tapo C200, drops frames)
  23, eda301d9 12, c199a97c 5; key.json sha256 b00aad4108c1b2a9... . The pause rule flags 1 of the 40, so stated in advance:
  the guardrail here is in effect Jev alone, and the pause rule is not tested in any useful way.
REPORTED: each rule alone; flagged share per operator reason; Jev's kind answer.
Run: .venv/bin/python scripts/eval_guardrail_fresh.py --build   (select, cut clips, contact sheets, review page)
     .venv/bin/python scripts/eval_guardrail_fresh.py --jev     (sends the 40 contact sheets to TypeSafe)
     .venv/bin/python scripts/eval_guardrail_fresh.py --score   (needs cache/guardrail_fresh/verdicts.txt)
Internal review of third-party venue footage; do not share.
"""
import collections, csv, glob, json, os, random, subprocess, sys, time
sys.path.insert(0, "."); sys.path.insert(0, "scripts")

SEED, N, PAD, JEV_CUT, T_PAUSE = 20261017, 40, 1.0, 0.4, 6.0
D, CLIPS = "cache/guardrail_fresh", "clips/guardrail_fresh"
KEY, JEV, VERD = f"{D}/key.json", f"{D}/jev.jsonl", f"{D}/verdicts.txt"


def pool():
    import validate_absolute_ranking as base
    from src.select import net_width_px, score_segments
    reviewed = json.load(open("cache/scale/dropped.json"))
    out = []
    for csvp in sorted(glob.glob("cache/scale/*.csv")):
        name = os.path.basename(csvp)[:-4]; meta = json.load(open(csvp[:-4] + ".meta.json")); calib = json.load(open(meta["calib"]))
        segs, cr, sp = base.detect(csvp, calib)
        segs = sorted(segs, key=lambda s: s["start"])
        for i, s in enumerate(segs):
            s["pre"] = s["start"] - segs[i - 1]["end"] if i > 0 else None
            s["post"] = segs[i + 1]["start"] - s["end"] if i + 1 < len(segs) else None
        skip = lambda s: any(d["session"] == name and abs(d["start"] - s["start"]) < 0.5 for d in reviewed)
        ranked = [s for s in score_segments(segs, cr, sp, net_width_px(calib)) if not skip(s)]
        for rank, s in enumerate(ranked[:2], 1):
            out.append({"session": name, "video": meta["path"], "start": s["start"], "end": s["end"], "rank": rank,
                        "pre": s["pre"], "post": s["post"],
                        "pause_flag": s["pre"] is not None and s["post"] is not None and s["pre"] <= T_PAUSE and s["post"] <= T_PAUSE})
    return out


def build():
    from cut_page import page
    import eval_jev_rally as K
    P = pool(); rng = random.Random(SEED); picks = rng.sample(P, min(N, len(P))); rng.shuffle(picks)
    print(f"pool {len(P)} (top 2 of {len(P) // 2}-ish sessions), picked {len(picks)}")
    os.makedirs(CLIPS, exist_ok=True); os.makedirs(D, exist_ok=True); K.SHEETS = f"{D}/sheets"
    for i, r in enumerate(picks, 401):
        r["clip"] = str(i); ss = max(0.0, r["start"] - PAD)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", r["video"], "-t", f"{r['end'] - ss + PAD:.3f}",
                        "-an", "-vf", "scale=-2:720", "-c:v", "libx264", "-crf", "30", "-preset", "veryfast", "-pix_fmt",
                        "yuv420p", f"{CLIPS}/{r['clip']}.mp4"], check=True)
        K.sheet({"id": r["clip"], "video": r["video"], "start": r["start"], "end": r["end"]})
    json.dump(picks, open(KEY, "w"), indent=1)
    open(f"{CLIPS}/index.html", "w").write(page([r["clip"] for r in picks], "Is it a rally? Clips 401-440"))
    print("clips, sheets, key and review page written")


def jev():
    from typesafe_sdk import Choice, Image, Noul, TypeSafeClient
    from eval_jev_ball import key
    import eval_jev_rally as K
    done = {json.loads(l)["clip"] for l in open(JEV)} if os.path.exists(JEV) else set()
    client = TypeSafeClient(api_key=key())
    for r in json.load(open(KEY)):
        if r["clip"] in done: continue
        img = Image(open(f"{D}/sheets/{r['clip']}.jpg", "rb").read()); t = time.time()
        res = client.system_one(model=K.MODEL, extra_headers=K.HDR, state={"clip": img}, questions=K.questions())
        a = res.answers
        rec = {"clip": r["clip"], "real": a["real"].noul, "kind": a["kind"].choice, "sec": round(time.time() - t, 2),
               "tok": res.usage.input_tokens, "otok": res.usage.output_tokens}
        open(JEV, "a").write(json.dumps(rec) + "\n"); print(r["clip"], f"real={rec['real']:.2f}", rec["kind"])


def score():
    key_ = {r["clip"]: r for r in json.load(open(KEY))}
    j = {r["clip"]: r for r in map(json.loads, open(JEV))}
    v = {}
    for part in open(VERD).read().replace("\n", ",").split(","):
        part = part.strip()
        if "=" not in part: continue
        c, rest = part.split("=", 1); verdict = rest.split("(")[0].strip()
        why = rest[rest.find("(") + 1:rest.rfind(")")].strip() if "(" in rest else ""
        v[c.strip()] = (verdict, why)
    rows = [dict(key_[c], verdict=vd, why=w, jev=j[c]["real"], kind=j[c]["kind"]) for c, (vd, w) in v.items() if vd != "unsure"]
    f_jev = lambda r: r["jev"] < JEV_CUT
    f_pause = lambda r: r["pause_flag"]
    f_both = lambda r: f_jev(r) or f_pause(r)
    real = [r for r in rows if r["verdict"] == "real"]; nr = [r for r in rows if r["verdict"] == "not"]; sh = [r for r in rows if r["verdict"] == "short"]
    print(f"judged {len(rows)}: real {len(real)}, not real {len(nr)}, very short {len(sh)}  (can't tell excluded: {sum(x[0] == 'unsure' for x in v.values())})")
    for name, f in (("Jev < 0.4", f_jev), ("pause rule", f_pause), ("GUARDRAIL (either)", f_both)):
        print(f"{name:20s} real flagged {sum(map(f, real))}/{len(real)}   not-real flagged {sum(map(f, nr))}/{len(nr)}   short flagged {sum(map(f, sh))}/{len(sh)}")
    print("by reason (guardrail):", {w or "not given": f"{sum(f_both(r) for r in nr if r['why'] == w)}/{sum(r['why'] == w for r in nr)}" for w in sorted({r['why'] for r in nr})})
    for vv in ("real", "not", "short"):
        print(f"Jev kind for {vv}:", dict(collections.Counter(r["kind"] for r in rows if r["verdict"] == vv)))
    lim = max(1, int(0.05 * len(real)))
    ok_r, ok_n = sum(map(f_both, real)) <= lim, sum(map(f_both, nr)) >= 0.5 * len(nr)
    under = len(nr) < 8
    print(f"\nreal half: {'pass' if ok_r else 'FAIL'} (limit {lim})   not-real half: "
          f"{'UNDERPOWERED' if under else ('pass' if ok_n else 'FAIL')}   ->  "
          f"{'FAIL' if not ok_r or (not under and not ok_n) else ('PASS' if not under else 'real half only: not a pass')}")


if __name__ == "__main__":
    {"--build": build, "--jev": jev, "--score": score}[sys.argv[1]]()
