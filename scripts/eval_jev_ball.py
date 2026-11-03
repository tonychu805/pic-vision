"""Test J: can Jev (TypeSafe System One, jev-1.14, image input + Box questions) find the ball in a single frame?
(2026-10-17, PIC-226). Pre-registered: this file and its bar were committed before any Jev call.

Operator's idea: use Jev's new image input to find the ball, as a possible alternative or check on TrackNet k14.
Jev sees one still frame (no motion), and its own docs warn that small targets in large images can be missed and that
images / Box are a prototype-grade feature, so this is a cheap feasibility probe, not a pipeline change.

GROUND TRUTH: the operator's hand-labelled bounces (ball position at the frame it lands; ball visible).
  chunk 2  c199a97c 0926 s002 (heavy glare): all 36 labels
  chunk 3c eda301d9 0926 s000 min 2-6 (no glare): every 3rd label in frame order -> 33
ARMS (same frames):
  k14     TrackNet k14 tile-arm top-1 detection at that frame (cache/bounce_pilot/*.tile.csv), the best k14 arm
  jev-A   whole frame, resized to 1568 px wide; Noul "pickleball visible" + Box "the pickleball in play"
  jev-B   the frame cut into 4 full-resolution quarter tiles (960x540, 64 px overlap). Call 1: Choice "which tile shows the
          pickleball in play" over the 4 tiles; call 2: Box on the chosen tile at full resolution (Jev docs' pattern)
HIT = predicted centre within 15 px of the label (source pixels; the bounce matching tolerance). Jev box centre counts
  regardless of the Noul answer; the Noul is reported.
REPORTED: hit rate per arm per chunk; on chunk 2, share of Jev box centres on the 4 known glare cells (20 px cells with
  >= 100 k14 hits); tokens and seconds per call.
BAR, fixed before any call: Jev is worth pursuing as a ball finder if its better arm (chosen per chunk is NOT allowed:
  one arm, the one with more total hits over both chunks) hits >= k14 on chunk 2 AND >= k14 - 10 percentage points on
  chunk 3c. Otherwise not, for single frames.
Key: TYPESAFE_API_KEY from the environment or ~/.config/typesafe.env (never printed).
Run: .venv/bin/python scripts/eval_jev_ball.py
"""
import collections, io, json, math, os, sys, time
sys.path.insert(0, ".")
import cv2
from PIL import Image as PILImage
from typesafe_sdk import Box, Choice, Image, Noul, TypeSafeClient
from src.tracknet import load_predictions

MODEL, TOL, HDR = "jev-1.14.0", 15.0, {"TypeSafe-Danger-Zone-Images": "true"}
CHUNKS = [
    ("chunk 2", "eval/labels/bounces/cvat_c199a97c_0926T0538_s002.json",
     "pgc-fieldtest-sept2026/c199a97c-c51f-4620-8523-b2837f48c1a7/2026-09-26T05-38-15-376Z/session-002.mkv",
     "cache/bounce_pilot/chunk2_c199a97c_0538_s002.tile.csv", 1),
    ("chunk 3c", "eval/labels/bounces/cvat_eda301d9_0926T0538_s000_120-360.json",
     "clips/bounce_chunk3/eda301d9_0926T0538_s000_120-360.mp4",
     "cache/bounce_pilot/chunk3c_eda301d9_0538_s000.tile.csv", 3),
]
OUT = "cache/jev_ball/results.jsonl"


def key():
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    for line in open(os.path.expanduser("~/.config/typesafe.env")):
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("no TYPESAFE_API_KEY")


def jpg(arr):
    b = io.BytesIO(); PILImage.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)).save(b, "JPEG", quality=92); return Image(b.getvalue())


def tiles(im):
    h, w = im.shape[:2]; tw, th, o = w // 2, h // 2, 32
    return {"top_left": (0, 0), "top_right": (w - tw - o, 0), "bottom_left": (0, h - th - o), "bottom_right": (w - tw - o, h - th - o)}, tw + o, th + o


def ask(client, state, questions):
    t = time.time()
    r = client.system_one(model=MODEL, state=state, questions=questions, extra_headers=HDR)
    return r, time.time() - t


def centre(box, w, h, x0=0, y0=0):
    b = box.box if hasattr(box, "box") else box["box"]
    g = (lambda k: getattr(b, k)) if hasattr(b, "top") else (lambda k: b[k])
    return x0 + (g("left") + g("right")) / 2 * w, y0 + (g("top") + g("bottom")) / 2 * h


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = {(r["chunk"], r["frame"]) for r in map(json.loads, open(OUT))} if os.path.exists(OUT) else set()
    client = TypeSafeClient(api_key=key())
    for name, labp, video, csv_, step in CHUNKS:
        labs = sorted(json.load(open(labp))["bounces"], key=lambda b: b["frame"])[::step]
        tr = load_predictions(csv_, 30.0); cap = cv2.VideoCapture(video)
        for b in labs:
            if (name, b["frame"]) in done: continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, b["frame"]); ok, im = cap.read()
            if not ok: print("decode fail", name, b["frame"]); continue
            H, W = im.shape[:2]; rec = {"chunk": name, "frame": b["frame"], "x": b["x"], "y": b["y"]}
            _, kx, ky, *_ = tr[b["frame"]]; rec["k14"] = None if kx is None else [kx, ky]
            small = cv2.resize(im, (1568, round(1568 * H / W)))
            r, s = ask(client, {"frame": jpg(small)}, {
                "visible": Noul(instructions="Is a pickleball (small yellow-green ball) visible in `frame`?"),
                "ball": Box(instructions="the pickleball in play (small yellow-green ball) in `frame`")})
            a = r.answers; rec["A"] = {"noul": a["visible"].noul, "conf": a["ball"].confidence,
                                      "xy": centre(a["ball"], W, H), "sec": round(s, 2), "tok": r.usage.input_tokens}
            org, tw, th = tiles(im)
            crops = {k: im[y0:y0 + th, x0:x0 + tw] for k, (x0, y0) in org.items()}
            r1, s1 = ask(client, {k: jpg(v) for k, v in crops.items()}, {
                "tile": Choice(instructions="Which image shows the pickleball in play (small yellow-green ball)?",
                               criteria={k: f"The ball is in `{k}`." for k in crops})})
            k = r1.answers["tile"].choice
            r2, s2 = ask(client, {"frame": jpg(crops[k])}, {
                "ball": Box(instructions="the pickleball in play (small yellow-green ball) in `frame`")})
            rec["B"] = {"tile": k, "tile_conf": r1.answers["tile"].confidence, "conf": r2.answers["ball"].confidence,
                        "xy": centre(r2.answers["ball"], tw, th, *org[k]), "sec": round(s1 + s2, 2),
                        "tok": r1.usage.input_tokens + r2.usage.input_tokens}
            open(OUT, "a").write(json.dumps(rec) + "\n"); print(name, b["frame"], "A", [round(v) for v in rec["A"]["xy"]], "B", [round(v) for v in rec["B"]["xy"]], "label", (b["x"], b["y"]))
    summarise()


def summarise():
    rows = [json.loads(l) for l in open(OUT)]
    hit = lambda p, r: p is not None and math.hypot(p[0] - r["x"], p[1] - r["y"]) <= TOL
    tr2 = load_predictions(CHUNKS[0][3], 30.0); cell = lambda x, y: (int(x // 20), int(y // 20))
    cnt = collections.Counter(cell(x, y) for _, x, y, *_ in tr2 if x is not None); glare = {c for c, v in cnt.items() if v >= 100}
    res = {}
    for name in ("chunk 2", "chunk 3c"):
        rs = [r for r in rows if r["chunk"] == name]; n = len(rs)
        res[name] = {a: sum(hit(r[a] if a == "k14" else r[a]["xy"], r) for r in rs) for a in ("k14", "A", "B")}
        print(f"{name}: n={n}  k14 {res[name]['k14']}  jev-A {res[name]['A']}  jev-B {res[name]['B']}  "
              f"(A noul>=0.5 on {sum(r['A']['noul'] >= 0.5 for r in rs)})")
        if name == "chunk 2":
            print(f"   on glare cells: k14 {sum(r['k14'] is not None and cell(*r['k14']) in glare for r in rs)}  "
                  f"jev-A {sum(cell(*r['A']['xy']) in glare for r in rs)}  jev-B {sum(cell(*r['B']['xy']) in glare for r in rs)}")
    print(f"per frame: jev-A {sum(r['A']['sec'] for r in rows) / len(rows):.1f}s {sum(r['A']['tok'] for r in rows) / len(rows):.0f} tok;  "
          f"jev-B {sum(r['B']['sec'] for r in rows) / len(rows):.1f}s {sum(r['B']['tok'] for r in rows) / len(rows):.0f} tok")
    arm = "A" if sum(res[c]["A"] for c in res) >= sum(res[c]["B"] for c in res) else "B"
    n2 = sum(r["chunk"] == "chunk 2" for r in rows); n3 = sum(r["chunk"] == "chunk 3c" for r in rows)
    ok = res["chunk 2"][arm] >= res["chunk 2"]["k14"] and res["chunk 3c"][arm] / n3 >= res["chunk 3c"]["k14"] / n3 - 0.10
    print(f"\nbetter Jev arm: {arm}  ->  {'PASS: worth pursuing' if ok else 'FAIL: not as a single-frame ball finder'}")


if __name__ == "__main__":
    summarise() if "--summary" in sys.argv else main()
