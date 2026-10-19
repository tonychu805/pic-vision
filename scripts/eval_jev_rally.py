"""Test K: Jev (TypeSafe jev-1.14, image input) as a rally guardrail: "is this a real point, or practice / ball
machine / failed serve / not play?" (2026-10-17, PIC-226). Pre-registered: this file and its bar were committed before
any Jev call; Jev has never been used on these clips, so they are held out for it.

GROUND TRUTH: the operator's playback verdicts on detected PGC rallies.
  96 top-sample / precision / blind-check clips (scripts/summarise_top_sample.py: real 60, not 25, short 10, unsure 1)
  30 fresh clips (cache/fresh_sample_key.csv, verdicts as eval_rally_formation.py: real 15, not 12, short 3)
  The one "unsure" is excluded. "short" (serve + return only) is reported, not gated.
INPUT per clip: one contact sheet, 6 frames evenly spaced over the detected rally ((i + 0.5) / 6 of its length), each
  784 x 441, laid out 2 wide x 3 high in time order (1568 x 1323), numbered 1-6.
QUESTIONS (one call per clip):
  real       Noul   "Is this a real point of a pickleball game ...?"
  kind       Choice real_point / practice / ball_machine / failed_serve / not_play (reported only)
RULE, fixed in advance: flag the clip when real < 0.5.
BAR: real clips flagged <= 3 of 75 (about 5%) AND not-real clips flagged >= 19 of 37 (half).
REPORTED: short clips flagged; flagged share per operator reason; Choice answers per verdict; the real-vs-not trade-off
  at other cut-offs (descriptive only, in-sample, not a pass); tokens and seconds per call.
Run: .venv/bin/python scripts/eval_jev_rally.py            (sheets are built locally; frames are sent to TypeSafe)
     .venv/bin/python scripts/eval_jev_rally.py --sheets   (build the contact sheets only, nothing sent)
     .venv/bin/python scripts/eval_jev_rally.py --summary  (score saved answers, nothing sent)
"""
import collections, csv, glob, io, json, os, sys, time
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import cv2
import numpy as np

MODEL, HDR = "jev-1.14.0", {"TypeSafe-Danger-Zone-Images": "true"}
SHEETS, OUT = "cache/jev_rally/sheets", "cache/jev_rally/results.jsonl"
TW, TH = 784, 441
FRESH = dict(x.split("=") for x in "301=not 302=not 303=real 304=short 305=short 306=not 307=real 308=not 309=real 310=real 311=not 312=short 313=real 314=not 315=real 316=not 317=real 318=real 319=not 320=not 321=real 322=not 323=real 324=not 325=real 326=real 327=real 328=not 329=real 330=real".split())
FRESH_WHY = {"301": "failed serve", "302": "failed serve", "306": "failed serve", "308": "failed serve", "316": "failed serve",
             "324": "ball hit the net", "328": "ball hit the net", "320": "serve only, cut off", "322": "serve only, cut off",
             "311": "not play", "314": "not play", "319": "practice"}
KINDS = {
    "real_point": "A real point of a game: a player serves from behind the baseline, the ball is returned, and players on both sides are in game positions.",
    "practice": "Warm-up, drilling or casual hitting: rallying without a serve, practice dinking at the kitchen, or a coach feeding balls by hand.",
    "ball_machine": "A ball machine is feeding balls to the players.",
    "failed_serve": "A point that ends at the serve or the return: the ball goes into the net or out and the players stop.",
    "not_play": "No play: people walking, picking up balls or standing around.",
}


def clips():
    import summarise_top_sample as S
    out = []
    for (sid, a, b), (verdict, why) in S.v.items():
        if verdict != "unsure":
            out.append({"id": f"{sid[:8]}_{a:.2f}", "video": f"cache/pgc_fieldtest/{sid}.mp4", "start": a, "end": b,
                        "verdict": verdict, "why": why or ("" if verdict == "real" else "not given")})
    for r in csv.DictReader(open("cache/fresh_sample_key.csv")):
        cam, ts, sess = r["segment"].split("_")
        vid = glob.glob(f"pgc-fieldtest-sept2026/{cam}*/{ts}*/{sess}.mkv")[0]
        out.append({"id": r["clip"], "video": vid, "start": float(r["start"]), "end": float(r["end"]),
                    "verdict": FRESH[r["clip"]], "why": FRESH_WHY.get(r["clip"], "")})
    return out


def sheet(c):
    p = f"{SHEETS}/{c['id']}.jpg"
    if os.path.exists(p): return p
    cap = cv2.VideoCapture(c["video"]); canvas = np.zeros((3 * TH, 2 * TW, 3), np.uint8)
    for i in range(6):
        cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * (c["start"] + (i + 0.5) / 6 * (c["end"] - c["start"])))
        ok, im = cap.read()
        if not ok: raise RuntimeError(f"decode {c['id']} frame {i}")
        t = cv2.resize(im, (TW, TH)); cv2.putText(t, str(i + 1), (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
        canvas[(i // 2) * TH:(i // 2 + 1) * TH, (i % 2) * TW:(i % 2 + 1) * TW] = t
    os.makedirs(SHEETS, exist_ok=True); cv2.imwrite(p, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90]); return p


def questions():
    from typesafe_sdk import Choice, Noul
    return {
        "real": Noul(instructions="`clip` shows six frames, numbered 1-6 in time order, from one fixed camera "
                                  "overlooking pickleball courts. Is this a real point of a pickleball game (served, "
                                  "returned and played out), rather than practice, a warm-up, a ball machine, a failed "
                                  "serve or no play? Judge only the main court (the largest court in the picture)."),
        "kind": Choice(instructions="`clip` shows six frames, numbered 1-6 in time order, from one fixed camera "
                                    "overlooking pickleball courts. What is happening on the main court (the largest "
                                    "court in the picture)?",
                       criteria=KINDS)}


def ask_all(cs):
    from typesafe_sdk import Choice, Image, Noul, TypeSafeClient
    from eval_jev_ball import key
    done = {json.loads(l)["id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    client = TypeSafeClient(api_key=key())
    for c in cs:
        if c["id"] in done: continue
        img = Image(open(sheet(c), "rb").read()); t = time.time()
        r = client.system_one(model=MODEL, extra_headers=HDR, state={"clip": img}, questions=questions())
        a = r.answers
        rec = {"id": c["id"], "verdict": c["verdict"], "why": c["why"], "real": a["real"].noul, "kind": a["kind"].choice,
               "kind_p": dict(a["kind"].probabilities), "sec": round(time.time() - t, 2), "tok": r.usage.input_tokens,
               "otok": r.usage.output_tokens}
        open(OUT, "a").write(json.dumps(rec) + "\n"); print(c["id"], c["verdict"], f"real={rec['real']:.2f}", rec["kind"])


def summarise():
    rows = [json.loads(l) for l in open(OUT)]
    g = lambda v: [r for r in rows if r["verdict"] == v]
    flag = lambda r, t=0.5: r["real"] < t
    real, nr, short = g("real"), g("not"), g("short")
    fr, fn, fs = sum(map(flag, real)), sum(map(flag, nr)), sum(map(flag, short))
    print(f"n={len(rows)}: real {len(real)}, not real {len(nr)}, short {len(short)}")
    print(f"flagged (real < 0.5): real {fr}/{len(real)} (bar <= 3)   not real {fn}/{len(nr)} (bar >= 19)   short {fs}/{len(short)}")
    print("by reason:", {w: f"{sum(flag(r) for r in nr if r['why'] == w)}/{sum(r['why'] == w for r in nr)}"
                         for w in sorted({r['why'] for r in nr})})
    for v in ("real", "not", "short"):
        print(f"Choice for {v}:", dict(collections.Counter(r["kind"] for r in g(v))))
    print("trade-off (descriptive, in-sample):")
    for t in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        print(f"   cut {t:.1f}: real flagged {sum(flag(r, t) for r in real):2d}/{len(real)}   not-real flagged {sum(flag(r, t) for r in nr):2d}/{len(nr)}")
    print(f"per call: {sum(r['sec'] for r in rows) / len(rows):.1f}s, {sum(r['tok'] for r in rows) / len(rows):.0f} input tokens")
    ok = fr <= 3 and fn >= 19
    print(f"\n{'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    cs = clips()
    if "--summary" in sys.argv: summarise()
    elif "--sheets" in sys.argv: [sheet(c) for c in cs]; print(len(cs), "sheets in", SHEETS)
    else: [sheet(c) for c in cs]; ask_all(cs); summarise()
