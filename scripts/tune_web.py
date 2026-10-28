#!/usr/bin/env python3
"""Watchability decision workbench (internal tool).

The project's objective is a reel you actually want to watch (PRD §1-§3), and
its own rule is that rally quality is judged from PLAYBACK, not numbers
(CLAUDE.md). So this tool is built around watching: load a cached session, set
the "what makes a highlight" recipe, and WATCH the top-N rallies it produces --
side by side against the SHIPPED config -- then record whether it got better.

Scoring signals live in a REGISTRY (`SIGNALS`): each is {key, label, weight,
shape params, normalize rule}. The Rank section renders one slider per signal and
score = sum(weight * normalized). Adding a signal later (e.g. real hit-count) is
a registry entry, not new UI. A startup self-check asserts the registry
reproduces src/select.rally_score at shipped weights, so it can't drift from
production. Runs the real detect chain; cuts preview clips with the production
cutter (src/render.clip_command). Read-only w.r.t. production.

Usage (from repo root, in the .venv):
    PYTHONPATH=. .venv/bin/python scripts/tune_web.py --port 8781
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import pathlib
import subprocess
import tempfile
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.ball import adaptive_gap_sec, cluster_crossings, crossing_times, net_line_y
from src.calib import court_wedge, court_x_range
from src.rallies import GAP_SEC, MIN_CROSSINGS
from src.render import clip_command
from src.select import frame_speeds, net_width_px, peak_rate, rally_score
import src.select as select
from src.track import max_jump_for_fps, reset_after_for_fps, track_ball
from src.tracknet import load_predictions

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIP_CACHE = ROOT / "cache" / "tune_clips"
VERDICTS = ROOT / "cache" / "watchability_verdicts.jsonl"
PAD_SEC = 3.0

# --- signal registry: the one place a ranking signal is defined ---------------
# Each: key, UI label, weight param + default, optional shape params (name,
# default, UI step), flags. `norm(feat, P)` -> 0..1 from the rally's measured
# features `feat` (dur, pcr, n_hard, swing) and the shape params `P`.
SIGNALS = [
    {"key": "len", "label": "Longer rallies", "wparam": "w_len", "wdef": float(select.SCORE_WEIGHTS[0]),
     "shape": [("length_sec", float(select.SCORE_LENGTH_SEC), 1)],
     "norm": lambda f, P: 1 - math.exp(-max(f["dur"], 0.0) / P["length_sec"])},
    {"key": "pace", "label": "Faster pace", "wparam": "w_pace", "wdef": float(select.SCORE_WEIGHTS[1]),
     "shape": [("pace_cap", float(select.SCORE_PACE_CAP), 0.25)],
     "norm": lambda f, P: min(1.0, max(f["pcr"], 0.0) / P["pace_cap"])},
    {"key": "hard", "label": "Hard shots", "wparam": "w_hard", "wdef": float(select.SCORE_WEIGHTS[2]),
     "shape": [("hard_half", float(select.SCORE_HARD_HALF), 1), ("hard_cutoff", float(select.SCORE_HARD_CUTOFF), 0.1)],
     "norm": lambda f, P: f["n_hard"] / (f["n_hard"] + P["hard_half"]) if f["n_hard"] > 0 else 0.0},
    {"key": "swing", "label": "Swings", "wparam": "w_swing", "wdef": 0.0, "warn": True, "needs_pose": True,
     "shape": [("swing_cutoff", 1.5, 0.1), ("swing_cap", 1.2, 0.1)],
     "norm": lambda f, P: (min(1.0, (f["swing"] or 0.0) / P["swing_cap"]) if f.get("swing") is not None else 0.0)},
    # Hits: RECONSTRUCTED (no committed ADR-157 rule) -- swing peaks that land
    # near a net-crossing (swing gated by ball activity). Default weight 0.
    {"key": "hits", "label": "Hits (reconstructed)", "wparam": "w_hits", "wdef": 0.0, "warn": True, "needs_pose": True,
     "shape": [("hit_cap", 1.2, 0.1), ("hit_window", 0.6, 0.1)],
     "norm": lambda f, P: (min(1.0, (f["hits"] or 0.0) / P["hit_cap"]) if f.get("hits") is not None else 0.0)},
]
SHAPE_PARAMS = [sp for s in SIGNALS for sp in s["shape"]]

DEFAULTS = {
    "gap_sec": GAP_SEC, "min_crossings": MIN_CROSSINGS, "fps": 30.0,
    "court_gate": "wedge", "court_margin": 50.0,
    "max_jump": round(max_jump_for_fps(30.0), 1), "reset_after": reset_after_for_fps(30.0),
    "band": 0.0, "adaptive_gap": 0, "n": 10,
    # Qualify / serve gate (reconstructed, camera-specific -> tune per session)
    "serve_gate": 0, "serve_net_y": 22.0, "serve_min_depth": 18.0,
}
for _s in SIGNALS:
    DEFAULTS[_s["wparam"]] = _s["wdef"]
for _name, _def, _step in SHAPE_PARAMS:
    DEFAULTS[_name] = _def


def score_rally(feat, P):
    """Registry score: sum(weight * normalized signal). `P` carries weights
    (w_*) and shape params."""
    return round(sum(float(P[s["wparam"]]) * s["norm"](feat, P) for s in SIGNALS), 1)


def _self_check():
    """Guard: the registry must reproduce src/select.rally_score at shipped
    weights (swing off), or the tool has silently drifted from production."""
    P = {s["wparam"]: s["wdef"] for s in SIGNALS}
    P.update({n: d for n, d, _ in SHAPE_PARAMS})
    for dur, pcr, nh in [(10, 1.0, 3), (22.0, 2.5, 10), (5, 0.2, 0), (15, 1.5, 7)]:
        mine = score_rally({"dur": dur, "pcr": pcr, "n_hard": nh, "swing": None}, P)
        ref = rally_score(dur, pcr, nh)
        assert abs(mine - ref) < 1e-6, "registry drift: %s vs rally_score %s (%s)" % (mine, ref, (dur, pcr, nh))


def _find_video(stem):
    vids = sorted((ROOT / "videos").glob(stem + "*.mp4"))
    if not vids:
        return None
    for pref in ("_fixed", "_30fps", "_full"):
        for v in vids:
            if pref in v.name:
                return str(v)
    return str(vids[0])


def _find_pose(stem):
    norm = "".join(c for c in stem.lower() if c.isalnum())
    for pf in sorted((ROOT / "cache" / "arm_swing").glob("poses_*.json")):
        tok = "".join(c for c in pf.name[len("poses_"):].split("_")[0].lower() if c.isalnum())
        if tok and tok in norm:
            return str(pf)
    return None


def discover_sessions():
    sessions = []
    fx = ROOT / "tests/fixtures/img7743_postbump_predictions.csv.gz"
    fx_calib = ROOT / "calib/IMG_7743_postbump_2900s-end_calib.json"
    if fx.exists() and fx_calib.exists():
        v = _find_video("IMG_7743_fixed") or _find_video("IMG_7743")
        sessions.append({"label": "IMG_7743 postbump (locked eval fixture)",
                         "calib": str(fx_calib), "csvs": [str(fx)], "video": v,
                         "pose": _find_pose("IMG_7743")})
    for calib in sorted((ROOT / "calib").glob("*_calib.json")):
        stem = calib.name[: -len("_calib.json")]
        csvs = [str(c) for c in sorted((ROOT / "cache").glob(stem + "*predictions*.csv"))]
        if csvs:
            sessions.append({"label": stem, "calib": str(calib), "csvs": csvs,
                             "video": _find_video(stem), "pose": _find_pose(stem)})
    return sessions


def signals_meta():
    return [{"key": s["key"], "label": s["label"], "wparam": s["wparam"], "weight": s["wdef"],
             "warn": s.get("warn", False), "needs_pose": s.get("needs_pose", False),
             "shape": [{"param": n, "value": d, "step": st} for n, d, st in s["shape"]]}
            for s in SIGNALS]


def _read_csv_path(csv_path):
    if str(csv_path).endswith(".gz"):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        with gzip.open(csv_path, "rt") as fh:
            tmp.write(fh.read())
        tmp.close()
        return tmp.name
    return str(csv_path)


def _truthy(v):
    return str(v).lower() in ("1", "true", "on", "yes")


_SWING_CACHE = {}


def swing_series(pose_path, fps, net_px):
    """RECONSTRUCTED per-frame fastest-wrist-motion series (net-widths/sec) from
    cached pose -- nearest-wrist match between consecutive frames. NOT the
    (uncommitted) validated swing detector; a transparent stand-in so swing can
    be tuned and WATCHED. Judge by playing clips, not by this number."""
    if pose_path in _SWING_CACHE:
        return _SWING_CACHE[pose_path]
    with open(pose_path) as f:
        poses = json.load(f)

    def wrists(persons):
        pts = []
        for person in persons:
            kp = person.get("kp") or []
            for idx in (9, 10):
                if idx < len(kp):
                    x, y, c = kp[idx]
                    if c and c > 0.3:
                        pts.append((x, y))
        return pts

    series, prev_t, prev_pts = [], None, []
    for fnum in sorted(poses, key=int):
        t = int(fnum) / fps
        pts = wrists(poses[fnum])
        if prev_t is not None and pts and prev_pts and t > prev_t:
            fastest = max(min(math.hypot(x - px, y - py) for px, py in prev_pts)
                          for x, y in pts) / (t - prev_t)
            series.append((t, fastest / net_px if net_px else 0.0))
        prev_t, prev_pts = t, pts
    _SWING_CACHE[pose_path] = series
    return series


def swing_peaks(series, cutoff, refractory=0.3):
    """Times of wrist-speed peaks >= cutoff, >= refractory s apart."""
    out, last = [], -1e9
    for t, sp in series:
        if sp >= cutoff and t - last >= refractory:
            out.append(t)
            last = t
    return out


def swing_rate(series, start, end, cutoff, refractory=0.3):
    dur = end - start
    pk = [t for t in swing_peaks(series, cutoff, refractory) if start <= t <= end]
    return len(pk) / dur if dur > 0 else 0.0


_COURT_CACHE = {}


def pose_court_series(pose_path, fps):
    """Per-frame list of players' court-y (depth) from cached pose."""
    if pose_path in _COURT_CACHE:
        return _COURT_CACHE[pose_path]
    with open(pose_path) as f:
        poses = json.load(f)
    out = []
    for fnum in sorted(poses, key=int):
        ys = [pp["court"][1] for pp in poses[fnum] if pp.get("court")]
        if ys:
            out.append((int(fnum) / fps, ys))
    _COURT_CACHE[pose_path] = out
    return out


def serve_depth(cseries, start, net_y, pre=1.0, win=3.0):
    """Max player depth (|court-y - net_y|) in the window around a rally start.
    Low = players never moved deep = looks like a serve/warm-up. RECONSTRUCTED
    from the Phase-1 serve gate (replay_phase1.py); thresholds are
    camera-specific, so they're knobs, not constants."""
    best = None  # None = no pose in this window -> can't judge, don't drop
    for t, ys in cseries:
        if start - pre <= t <= start + win:
            for y in ys:
                d = abs(y - net_y)
                best = d if best is None else max(best, d)
    return best


def compute(p):
    csv_path = _read_csv_path(p["csv"])
    with open(p["calib"]) as f:
        calib = json.load(f)
    if p.get("court_gate", "wedge") == "flat":
        xmin, xmax = court_x_range(calib, margin_px=float(p["court_margin"]))
        in_court = lambda x, y: x is not None and xmin <= x <= xmax
        gate = "flat court_x_range [%.0f, %.0f]" % (xmin, xmax)
    else:
        in_court = court_wedge(calib)
        gate = "court_wedge"
    net_y = net_line_y(calib)
    net_px = net_width_px(calib)
    fps = float(p["fps"])

    track = load_predictions(csv_path, fps)
    times = [t for t, *_ in track]
    frames = [[(x, y, c if c is not None else 1.0)] if in_court(x, y) else []
              for _, x, y, w, h, c in track]
    ys = track_ball(frames, max_jump=float(p["max_jump"]), reset_after=int(float(p["reset_after"])))
    times_crossed = crossing_times(list(zip(times, ys)), net_y=net_y, band=float(p["band"]))
    gap, mc = float(p["gap_sec"]), int(p["min_crossings"])
    if _truthy(p.get("adaptive_gap", 0)):
        gap, segments = adaptive_gap_sec(times_crossed, min_crossings=mc, base_gap=gap)
    else:
        segments = cluster_crossings(times_crossed, gap_sec=gap, min_crossings=mc)
    raw = sorted([(t, x, y) for t, x, y, w, h, c in track if in_court(x, y)], key=lambda q: q[0])
    speeds = frame_speeds(raw)

    # pose-derived signals (reconstructed) if pose available
    series = cseries = None
    pose_path = p.get("pose") or ""
    if pose_path and os.path.exists(pose_path):
        try:
            series = swing_series(pose_path, fps, net_px)
            cseries = pose_court_series(pose_path, fps)
        except Exception:
            series = cseries = None

    # shape + weight params for the registry
    P = {s["wparam"]: float(p[s["wparam"]]) for s in SIGNALS}
    for name, dflt, _ in SHAPE_PARAMS:
        P[name] = float(p.get(name, dflt))
    hard_cut, swing_cut, hit_window = P["hard_cutoff"], P["swing_cutoff"], P["hit_window"]
    peaks_all = swing_peaks(series, swing_cut) if series is not None else None

    # Qualify: serve gate (reconstructed; thresholds are knobs, not constants)
    dropped = 0
    if _truthy(p.get("serve_gate", 0)) and cseries is not None:
        net_y_s = float(p.get("serve_net_y", 22.0))
        min_d = float(p.get("serve_min_depth", 18.0))
        kept = []
        for s in segments:
            d = serve_depth(cseries, s["start"], net_y_s)
            if d is None or d >= min_d:   # keep if can't judge (no pose) or deep enough
                kept.append(s)
        dropped = len(segments) - len(kept)
        segments = kept

    rows = []
    for s in segments:
        start, end = s["start"], s["end"]
        seg_cross = [t for t in times_crossed if start <= t <= end]
        pcr = peak_rate(seg_cross, start, end)
        n_hard = sum(1 for t, v in speeds if start <= t <= end and net_px and v / net_px >= hard_cut)
        sw = swing_rate(series, start, end, swing_cut) if series is not None else None
        hits = None
        if peaks_all is not None:
            dur0 = end - start
            hc = sum(1 for t in peaks_all if start <= t <= end and any(abs(t - c) <= hit_window for c in seg_cross))
            hits = hc / dur0 if dur0 > 0 else 0.0
        feat = {"dur": end - start, "pcr": pcr, "n_hard": n_hard, "swing": sw, "hits": hits}
        rows.append({"start": start, "end": end, "duration": end - start,
                     "peak_crossing_rate": round(pcr, 2), "n_hard": n_hard,
                     "swing": round(sw, 2) if sw is not None else None,
                     "hits": round(hits, 2) if hits is not None else None,
                     "score": score_rally(feat, P)})
    rows.sort(key=lambda r: -r["score"])
    n = int(p["n"])
    out = [{"rank": i + 1, "start": round(r["start"], 1), "end": round(r["end"], 1),
            "duration": round(r["duration"], 1), "peak_crossing_rate": r["peak_crossing_rate"],
            "n_hard": r["n_hard"], "swing": r["swing"], "hits": r["hits"], "score": r["score"]}
           for i, r in enumerate(rows[:n])]
    return {"n_candidates": len(segments), "dropped_serve": dropped,
            "net_px": round(net_px, 1) if net_px else None,
            "gate": gate, "gap_used": round(gap, 2), "has_pose": series is not None, "rows": out}


def cut_clip(video, start, end):
    start = max(0.0, float(start) - PAD_SEC)
    end = float(end) + PAD_SEC
    CLIP_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(("%s|%.2f|%.2f" % (video, start, end)).encode()).hexdigest()[:16]
    out = CLIP_CACHE / (key + ".mp4")
    if not out.exists() or out.stat().st_size == 0:
        subprocess.run(clip_command(video, start, end, str(out)), check=True)
    return str(out)


def _safe_video(path):
    rp = pathlib.Path(path).resolve()
    return rp.exists() and rp.suffix == ".mp4" and str(rp).startswith(str(ROOT))


PAGE = r"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Watchability workbench</title>
<style>
  :root{color-scheme:dark}
  body{font:14px system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
  header{padding:10px 16px;background:#171a21;border-bottom:1px solid #2a2f3a}
  .meta{color:#9aa4b2;font-size:12px}.warn{color:#ffcf6b}
  .wrap{display:flex;gap:16px;padding:16px;flex-wrap:wrap;align-items:flex-start}
  .panel{background:#171a21;border:1px solid #2a2f3a;border-radius:8px;padding:14px}
  .knobs{flex:0 0 300px}
  select,input[type=number]{width:100%;box-sizing:border-box;background:#0f1115;color:#e6e6e6;border:1px solid #2a2f3a;border-radius:6px;padding:6px}
  .sec{border:1px solid #2a2f3a;border-radius:8px;margin-top:10px}
  .sec>summary{cursor:pointer;padding:9px 11px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#cbd3df;background:#1b212b;border-radius:8px}
  .sec[open]>summary{border-bottom:1px solid #2a2f3a;border-radius:8px 8px 0 0}
  .sbody{padding:11px}
  .slider{margin:9px 0}
  .sl{display:flex;justify-content:space-between;align-items:baseline;font-size:13px}
  .sl b{color:#2a6df4}
  input[type=range]{width:100%;accent-color:#2a6df4;margin-top:3px}
  details.adv{margin-top:10px;border-top:1px solid #222;padding-top:8px}
  details.adv>summary{cursor:pointer;color:#9aa4b2;font-size:12px}
  label{display:block;margin:7px 0 2px;color:#9aa4b2;font-size:11px}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .cols{flex:1 1 560px;display:flex;gap:14px}.col{flex:1;min-width:0}
  .rlist{display:flex;flex-direction:column}
  .rl{display:grid;grid-template-columns:30px 112px 1fr 54px 44px 26px;align-items:center;gap:7px;padding:4px 3px;border-bottom:1px solid #1b2028;font-size:12px}
  .rl.new{box-shadow:inset 3px 0 0 #2ea043;background:#102a18}.rl.dropped{opacity:.4}
  .rk{color:#6b7482}.tm{color:#cbd3df;white-space:nowrap}
  .scbar{height:13px;background:#222;border-radius:3px;overflow:hidden}.scbar>span{display:block;height:100%;background:#2a6df4}
  .scv{text-align:right;font-weight:700}
  .swbar{height:7px;background:#222;border-radius:3px;overflow:hidden}.swbar>span{display:block;height:100%;background:#ffcf6b}
  .nosw{color:#4a515c;text-align:center}.up{color:#7ee787}.down{color:#ff9797}
  button{background:#2a6df4;color:#fff;border:0;border-radius:6px;padding:7px 11px;cursor:pointer}
  button.ghost{background:#2a2f3a}button.play{background:#2a2f3a;padding:1px 6px;font-size:12px}
  video{width:100%;border-radius:8px;background:#000;margin-top:8px}
  .verdict{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
  .verdict .b{background:#2ea043}.verdict .w{background:#c24141}.verdict .s{background:#444}
  .gloss{columns:2;column-gap:30px;margin-top:8px}@media(max-width:820px){.gloss{columns:1}}
  .gloss h4{font-size:12px;color:#7fb0ff;margin:12px 0 4px;break-after:avoid;text-transform:uppercase}
  .gloss dt{color:#e6e6e6;font-weight:600;margin-top:7px;break-inside:avoid}.gloss dd{margin:0;color:#9aa4b2;font-size:12px;break-inside:avoid}
  code{color:#cbd3df;background:#0f1115;border:1px solid #2a2f3a;border-radius:4px;padding:0 4px}
</style>
<header><b>Watchability workbench</b> &nbsp;<span class=meta>set the recipe → watch the top rallies → is it a better reel? the <b>▶</b> is the verdict, not the score</span></header>
<div class=wrap>
  <div class="panel knobs">
    <select id=session></select>
    <select id=predict style="margin-top:6px"></select>
    <div class=meta id=sessmeta style="margin-top:6px"></div>

    <details class=sec open><summary>Rank — which rallies win</summary><div class=sbody>
      <div class=meta>what makes a highlight (slider = weight, 0–100)</div>
      <div id=recipe></div>
      <div class=slider><div class=sl><span>Show top</span><b id=v_n></b></div><input id=n type=range min=3 max=20></div>
      <details class=adv><summary>Advanced — detection + score shape</summary>
        <div class=row2><div><label>gap_sec</label><input id=gap_sec type=number step=0.5></div><div><label>min_crossings</label><input id=min_crossings type=number step=1></div></div>
        <label>court gate</label><select id=court_gate><option value=wedge>court_wedge (shipped)</option><option value=flat>flat court_x_range</option></select>
        <div class=row2><div><label>court_margin</label><input id=court_margin type=number step=5></div><div><label>band</label><input id=band type=number step=1></div></div>
        <div class=row2><div><label>max_jump</label><input id=max_jump type=number step=5></div><div><label>reset_after</label><input id=reset_after type=number step=1></div></div>
        <div style="display:flex;gap:6px;align-items:center;margin:8px 0"><input id=adaptive_gap type=checkbox style="width:auto"><label style="margin:0">adaptive_gap</label></div>
        <label>fps</label><input id=fps type=number step=1>
        <div class=meta style="margin-top:10px">score shape (per signal)</div>
        <div id=shape class=row2></div>
      </details>
    </div></details>

    <details class=sec><summary>Qualify — drop serves / warm-up <span class=warn style="text-transform:none">(reconstructed)</span></summary><div class=sbody>
      <div style="display:flex;gap:6px;align-items:center"><input id=serve_gate type=checkbox style="width:auto"><label style="margin:0">serve gate on</label></div>
      <div class=row2><div><label>net court-y</label><input id=serve_net_y type=number step=1></div><div><label>min depth</label><input id=serve_min_depth type=number step=1></div></div>
      <div class=meta>drops rallies where no player moved past <code>min depth</code> from the net near the start (looks like a serve/warm-up). Thresholds are camera-specific — tune by watching the dropped clips. Needs ✋ pose.</div>
    </div></details>

    <div style="display:flex;gap:8px;margin-top:12px"><button onclick=run()>Recompute</button><button class=ghost onclick=reset()>Reset to shipped</button></div>
  </div>

  <div class="panel cols">
    <div class=col><div class=meta><b>Shipped</b> <span id=ms></span></div><div id=shipped class=rlist></div></div>
    <div class=col><div class=meta><b>Candidate</b> <span id=mc></span></div><div id=cand class=rlist></div></div>
  </div>

  <div class=panel style="flex:0 0 340px">
    <div class=meta id=playmeta>click ▶ on a rally to watch it</div>
    <video id=player controls preload=none></video>
    <div id=novideo class="meta warn" hidden>No local video for this session — numbers only.</div>
    <div class=verdict><span class=meta>Candidate vs shipped:</span>
      <button class=b onclick="verdict('better')">Better</button>
      <button class=s onclick="verdict('same')">Same</button>
      <button class=w onclick="verdict('worse')">Worse</button></div>
    <div class=meta id=vstatus></div>
  </div>

  <div class=panel style="flex:1 1 100%">
    <details><summary><b>📖 Glossary</b> — what each control & readout means</summary>
    <div class=gloss>
      <h4>Rank — what makes a highlight (score = these, weighted)</h4>
      <dl>
        <dt>Longer rallies</dt><dd>weight on duration.</dd>
        <dt>Faster pace</dt><dd>weight on peak crossing rate (net-crossings/sec in the busiest ~3s).</dd>
        <dt>Hard shots</dt><dd>weight on how many balls exceed a speed threshold (net-widths/sec).</dd>
        <dt>Swings</dt><dd>weight on arm-swing activity (reconstructed from pose). 0 = shipped. Judge by watching.</dd>
        <dt>Show top</dt><dd>how many ranked rallies to list.</dd>
      </dl>
      <h4>Advanced — how a rally is detected</h4>
      <dl>
        <dt><code>gap_sec</code></dt><dd>max seconds between net-crossings in one rally. Larger merges, smaller splits.</dd>
        <dt><code>min_crossings</code></dt><dd>fewest crossings to count as a rally. Higher = stricter.</dd>
        <dt>court gate</dt><dd><code>court_wedge</code> perspective (shipped) vs <code>flat court_x_range</code> (looser).</dd>
        <dt><code>court_margin</code> / <code>band</code></dt><dd>flat-gate padding / net-crossing jitter slack (px).</dd>
        <dt><code>max_jump</code> / <code>reset_after</code></dt><dd>tracker teleport reject (px) / frames before re-acquiring.</dd>
        <dt><code>adaptive_gap</code></dt><dd>derive gap_sec from the session's own rallies (PIC-33).</dd>
        <dt>score shape</dt><dd><code>length_sec</code>/<code>pace_cap</code>/<code>hard_half</code>/<code>hard_cutoff</code>/<code>swing_cutoff</code>/<code>swing_cap</code> — the curves that turn each raw measurement into its 0–1 value.</dd>
      </dl>
      <h4>Reading the columns</h4>
      <dl>
        <dt>Shipped vs Candidate</dt><dd>production defaults vs your knobs; same session, so differences are your config.</dd>
        <dt>blue bar</dt><dd>0–100 score at the current recipe.</dd>
        <dt>amber bar</dt><dd>reconstructed swing rate; <code>–</code> = no pose.</dd>
        <dt>green / faded</dt><dd>rally entered / dropped from the top-N vs shipped. ▲/▼ = score delta.</dd>
        <dt>▶</dt><dd>cut &amp; play (needs 🎬 video). First play ~5s, then cached.</dd>
        <dt>🎬 / ✋</dt><dd>session has local video / pose.</dd>
      </dl>
    </div>
    </details>
  </div>
</div>
<script>
const DET=["gap_sec","min_crossings","fps","court_margin","band","max_jump","reset_after","serve_net_y","serve_min_depth","n"];
const CHK=["court_gate","adaptive_gap","serve_gate"];
let DEFAULTS={},SESSIONS=[],SIGNALS=[],NUM=[],LBL=[],LAST={};
function sess(){return SESSIONS[document.getElementById("session").value]||{};}
function curParams(){const o={};NUM.forEach(k=>o[k]=document.getElementById(k).value);o.court_gate=document.getElementById("court_gate").value;o.adaptive_gap=document.getElementById("adaptive_gap").checked?1:0;o.serve_gate=document.getElementById("serve_gate").checked?1:0;return o;}
function shippedParams(){const o={};NUM.forEach(k=>o[k]=DEFAULTS[k]);o.court_gate=DEFAULTS.court_gate;o.adaptive_gap=DEFAULTS.adaptive_gap;o.serve_gate=DEFAULTS.serve_gate;o.n=document.getElementById("n").value;return o;}
function syncLabels(){LBL.forEach(k=>{const e=document.getElementById("v_"+k);if(e)e.textContent=document.getElementById(k).value;});}
async function init(){
  DEFAULTS=await (await fetch("/defaults")).json();
  SIGNALS=await (await fetch("/signals")).json();
  SESSIONS=await (await fetch("/sessions")).json();
  // build recipe sliders + shape inputs from the signal registry (data-driven)
  document.getElementById("recipe").innerHTML=SIGNALS.map(s=>
    `<div class=slider><div class=sl><span class="${s.warn?'warn':''}">${s.label}</span><b id=v_${s.wparam}></b></div><input id=${s.wparam} type=range min=0 max=100></div>`).join("");
  document.getElementById("shape").innerHTML=SIGNALS.flatMap(s=>s.shape.map(sh=>
    `<div><label>${sh.param}</label><input id=${sh.param} type=number step=${sh.step}></div>`)).join("");
  NUM=SIGNALS.flatMap(s=>[s.wparam,...s.shape.map(sh=>sh.param)]).concat(DET);
  LBL=SIGNALS.map(s=>s.wparam).concat(["n"]);
  const sel=document.getElementById("session");
  SESSIONS.forEach((s,i)=>{const o=document.createElement("option");o.value=i;o.textContent=s.label+(s.video?" 🎬":"")+(s.pose?" ✋":"");sel.appendChild(o);});
  sel.onchange=()=>{fillVariants();meta();run();};
  document.getElementById("predict").onchange=run;
  reset();fillVariants();meta();run();
}
function fillVariants(){const pd=document.getElementById("predict");pd.innerHTML="";(sess().csvs||[]).forEach(c=>{const o=document.createElement("option");o.value=c;o.textContent=c.split("/").pop();pd.appendChild(o);});}
function meta(){const s=sess();document.getElementById("sessmeta").textContent=(s.video?"🎬 video":"no video")+(s.pose?" · ✋ pose":" · no pose");document.getElementById("novideo").hidden=!!s.video;}
function reset(){NUM.forEach(k=>{if(DEFAULTS[k]!==undefined)document.getElementById(k).value=DEFAULTS[k];});document.getElementById("court_gate").value=DEFAULTS.court_gate;document.getElementById("adaptive_gap").checked=!!Number(DEFAULTS.adaptive_gap);document.getElementById("serve_gate").checked=!!Number(DEFAULTS.serve_gate);syncLabels();}
function q(base){const s=sess();const p=new URLSearchParams({csv:document.getElementById("predict").value,calib:s.calib,pose:s.pose||""});Object.entries(base).forEach(([k,v])=>p.set(k,v));return p.toString();}
async function run(){
  const s=sess();if(!s.csvs)return;
  const [shp,cnd]=await Promise.all([
    (await fetch("/compute?"+q(shippedParams()))).json(),
    (await fetch("/compute?"+q(curParams()))).json()]);
  if(shp.error||cnd.error){document.getElementById("ms").textContent=shp.error||cnd.error;return;}
  LAST={shipped:shp,candidate:cnd,video:s.video,session:s.label,config:curParams()};
  render();
}
function matchByTime(row,other){return other.find(o=>Math.abs(o.start-row.start)<3);}
function rowHtml(r,cls,delta,vid){
  const sc=Math.max(0,Math.min(100,r.score||0));
  const play=vid?`<button class=play onclick="watch(${r.start},${r.end})">▶</button>`:"<span></span>";
  const d=delta!=null?` <span class=${delta>=0?'up':'down'}>${delta>=0?'▲':'▼'}${Math.abs(delta).toFixed(0)}</span>`:"";
  const sw=r.swing==null?`<span class=nosw>–</span>`:`<span class=swbar><span style="width:${Math.min(100,r.swing/2*100)}%"></span></span>`;
  return `<div class="rl ${cls}"><span class=rk>#${r.rank}</span><span class=tm>${r.start}–${r.end}·${Math.round(r.duration)}s</span>`
    +`<span class=scbar><span style="width:${sc}%"></span></span><span class=scv>${r.score}${d}</span>${sw}${play}</div>`;
}
function render(){
  const {shipped,candidate,video}=LAST;
  document.getElementById("ms").textContent=`${shipped.n_candidates} found`;
  document.getElementById("mc").textContent=`${candidate.n_candidates} found`+(candidate.dropped_serve?` · ${candidate.dropped_serve} served-out`:"");
  document.getElementById("shipped").innerHTML=shipped.rows.map(r=>rowHtml(r,matchByTime(r,candidate.rows)?"":"dropped",null,video)).join("");
  document.getElementById("cand").innerHTML=candidate.rows.map(r=>{const m=matchByTime(r,shipped.rows);return rowHtml(r,m?"":"new",m?r.score-m.score:null,video);}).join("");
}
async function watch(start,end){
  const v=LAST.video;if(!v)return;
  const p=document.getElementById("player");
  document.getElementById("playmeta").textContent=`cutting ${start}–${end}s …`;
  p.src="/clip?"+new URLSearchParams({video:v,start,end});p.load();
  p.oncanplay=()=>document.getElementById("playmeta").textContent=`rally ${start}–${end}s`;
  p.play().catch(()=>{});
}
async function verdict(v){
  const r=await fetch("/verdict",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({verdict:v,session:LAST.session,config:LAST.config,
      shipped_top:(LAST.shipped.rows||[]).map(x=>x.start),candidate_top:(LAST.candidate.rows||[]).map(x=>x.start)})});
  document.getElementById("vstatus").textContent=(await r.json()).ok?("recorded: "+v):"error";
}
document.addEventListener("input",e=>{if(e.target&&(NUM.includes(e.target.id)||CHK.includes(e.target.id))){syncLabels();clearTimeout(window._t);window._t=setTimeout(run,400);}});
document.addEventListener("change",e=>{if(e.target&&CHK.includes(e.target.id))run();});
init();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mp4(self, path):
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        with open(path, "rb") as f:
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else 0
                end = int(b) if b else size - 1
                end = min(end, size - 1)
                f.seek(start)
                data = f.read(end - start + 1)
                self.send_response(206)
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            else:
                data = f.read()
                self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/defaults":
            self._json(DEFAULTS)
        elif u.path == "/signals":
            self._json(signals_meta())
        elif u.path == "/sessions":
            self._json(discover_sessions())
        elif u.path == "/compute":
            try:
                self._json(compute(q))
            except Exception as e:
                self._json({"error": "%s: %s" % (type(e).__name__, e)})
        elif u.path == "/clip":
            try:
                if not _safe_video(q.get("video", "")):
                    self._json({"error": "bad video path"}, 400); return
                self._serve_mp4(cut_clip(q["video"], q["start"], q["end"]))
            except Exception as e:
                self._json({"error": "%s: %s" % (type(e).__name__, e)})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/verdict":
            ln = int(self.headers.get("Content-Length", 0))
            try:
                rec = json.loads(self.rfile.read(ln) or b"{}")
                rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                VERDICTS.parent.mkdir(parents=True, exist_ok=True)
                with open(VERDICTS, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
        else:
            self.send_response(404); self.end_headers()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8781)
    args = ap.parse_args()
    _self_check()
    ss = discover_sessions()
    print("registry self-check OK · watchability workbench on http://localhost:%d  (sessions: %d, video: %d, pose: %d)"
          % (args.port, len(ss), sum(1 for s in ss if s["video"]), sum(1 for s in ss if s["pose"])))
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
