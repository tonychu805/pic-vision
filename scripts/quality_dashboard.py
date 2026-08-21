#!/usr/bin/env python3
"""
Local dashboard for the highlight-worthy signal question (PIC-7/PIC-45):
toggle which candidate signals are "activated," see how well the combined,
equally-weighted, per-session z-scored signal separates quality grade 1
(highlight) from grade 2 (ordinary) on each dev session, and keep a history
of combinations tried. Same local-HTTP-server style as label_web.py /
calibrate_web.py -- no framework, LAN/Tailscale accessible.

Data comes from cache/quality_signals.json (scripts/compute_quality_signals.py
-- rerun that first, or after labelling/grading a new session). Dev sessions
only; IMG_7743 is locked eval (LABELING.md) and is not in the signals cache.

Usage (run from repo root):
    python scripts/quality_dashboard.py --port 8766
"""
import argparse
import json
import statistics
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

SIGNALS = ["duration", "crossing_count", "motion_mean", "motion_max",
           "kitchen_mean", "kitchen_both_up_frac"]
SIGNAL_LABELS = {
    "duration": "Duration (length/intensity)",
    "crossing_count": "Crossing count (length/intensity, PIC-7's existing 0.73 result)",
    "motion_mean": "Mean player motion (momentum swing, built/unwired)",
    "motion_max": "Peak player motion (skill display proxy, weak)",
    "kitchen_mean": "Mean players-at-kitchen (sustained tension, built/unwired)",
    "kitchen_both_up_frac": "Fraction of rally both teams at kitchen",
}
LOW_CONFIDENCE_N = 5   # fewer grade-1 examples than this -> flag, don't trust
HISTORY_PATH = "cache/quality_dashboard_history.jsonl"

STATE = {}


def load_rows(path):
    with open(path) as f:
        return json.load(f)


def zscore_within_session(rows, signals):
    """z-score each active signal within its own session (PIC-7: raw
    thresholds don't transfer across format; per-session normalization is
    what makes combining signals across brickwall/pb_draft_cup/IMG_7744 not
    meaningless)."""
    by_session = {}
    for r in rows:
        by_session.setdefault(r["session"], []).append(r)
    scored = []
    for session, srows in by_session.items():
        stats = {}
        for sig in signals:
            vals = [row[sig] for row in srows]
            mean = statistics.mean(vals)
            stdev = statistics.pstdev(vals) or 1.0
            stats[sig] = (mean, stdev)
        for row in srows:
            combined = sum((row[sig] - stats[sig][0]) / stats[sig][1] for sig in signals) \
                if signals else 0.0
            scored.append({**row, "combined": combined})
    return scored


def best_threshold_balanced_acc(values, grades):
    cands = sorted(set(values))
    mids = [(a + b) / 2 for a, b in zip(cands, cands[1:])] or cands
    n1 = sum(1 for g in grades if g == 1)
    n2 = sum(1 for g in grades if g == 2)
    best = (0.5, None)
    for t in mids:
        tp = sum(1 for v, g in zip(values, grades) if v >= t and g == 1)
        tn = sum(1 for v, g in zip(values, grades) if v < t and g == 2)
        sens = tp / n1 if n1 else 0.0
        spec = tn / n2 if n2 else 0.0
        bal = (sens + spec) / 2
        if bal > best[0]:
            best = (bal, t)
    return best


def score_combination(rows, active_signals):
    if not active_signals:
        return {"per_session": {}, "active": []}
    scored = zscore_within_session(rows, active_signals)
    by_session = {}
    for r in scored:
        by_session.setdefault(r["session"], []).append(r)

    per_session = {}
    for session, srows in by_session.items():
        n1 = sum(1 for r in srows if r["grade"] == 1)
        n2 = sum(1 for r in srows if r["grade"] == 2)
        bal, t = best_threshold_balanced_acc(
            [r["combined"] for r in srows], [r["grade"] for r in srows])
        per_session[session] = {
            "balanced_acc": round(bal, 3), "threshold": round(t, 3) if t is not None else None,
            "n_grade1": n1, "n_grade2": n2,
            "low_confidence": n1 < LOW_CONFIDENCE_N or n2 < LOW_CONFIDENCE_N,
        }
    return {"per_session": per_session, "active": active_signals}


def log_history(result):
    entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **result}
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def read_history(limit=15):
    try:
        with open(HISTORY_PATH) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    return [json.loads(l) for l in lines[-limit:]][::-1]


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Highlight-signal dashboard</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2em auto; color: #222; }}
h1 {{ font-size: 1.3em; }}
label {{ display: block; margin: 0.4em 0; cursor: pointer; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
th, td {{ text-align: left; padding: 0.3em 0.6em; border-bottom: 1px solid #ddd; }}
.low {{ color: #b30; }}
.low::after {{ content: " (low confidence, n<{low_n})"; font-size: 0.85em; }}
#hist td {{ font-size: 0.85em; color: #555; }}
.note {{ color: #555; font-size: 0.9em; }}
</style></head><body>
<h1>Highlight-worthy signal dashboard (PIC-7 / PIC-45)</h1>
<p class="note">Toggle signals, see per-session balanced accuracy separating quality grade 1 (highlight)
from grade 2 (ordinary). Signals z-scored within each session (formats don't share raw thresholds
&mdash; PIC-7). Sessions with under {low_n} examples of either grade are flagged, not trusted &mdash;
small-n threshold fits overfit easily (see EXPERIMENTS.md 2026-08-20).</p>
<div id="signals"></div>
<table id="results"><thead><tr><th>session</th><th>balanced acc</th><th>n grade1</th><th>n grade2</th></tr></thead>
<tbody></tbody></table>
<h3>History</h3>
<table id="hist"><thead><tr><th>when</th><th>active signals</th><th>result</th></tr></thead>
<tbody></tbody></table>
<script>
const SIGNALS = {signals_json};
const LABELS = {labels_json};
const div = document.getElementById('signals');
SIGNALS.forEach(s => {{
  const l = document.createElement('label');
  const cb = document.createElement('input');
  cb.type = 'checkbox'; cb.value = s; cb.checked = true;
  cb.addEventListener('change', score);
  l.appendChild(cb);
  l.appendChild(document.createTextNode(' ' + LABELS[s]));
  div.appendChild(l);
}});

function score() {{
  const active = Array.from(div.querySelectorAll('input:checked')).map(cb => cb.value);
  fetch('/score', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{active}})}})
    .then(r => r.json()).then(render);
}}

function render(d) {{
  const tb = document.querySelector('#results tbody');
  tb.innerHTML = '';
  Object.entries(d.per_session || {{}}).forEach(([session, r]) => {{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="${{r.low_confidence ? 'low' : ''}}">${{session}}</td>` +
      `<td>${{r.balanced_acc}}</td><td>${{r.n_grade1}}</td><td>${{r.n_grade2}}</td>`;
    tb.appendChild(tr);
  }});
  loadHistory();
}}

function loadHistory() {{
  fetch('/history').then(r => r.json()).then(hist => {{
    const tb = document.querySelector('#hist tbody');
    tb.innerHTML = '';
    hist.forEach(h => {{
      const tr = document.createElement('tr');
      const summary = Object.entries(h.per_session || {{}})
        .map(([s, r]) => s + '=' + r.balanced_acc + (r.low_confidence ? '*' : '')).join(', ');
      tr.innerHTML = `<td>${{h.ts}}</td><td>${{(h.active || []).join(', ') || '(none)'}}</td><td>${{summary}}</td>`;
      tb.appendChild(tr);
    }});
  }});
}}

score();
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.format(
                signals_json=json.dumps(SIGNALS), labels_json=json.dumps(SIGNAL_LABELS),
                low_n=LOW_CONFIDENCE_N).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/history":
            self._json(read_history())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/score":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length))
        active = [s for s in data.get("active", []) if s in SIGNALS]
        result = score_combination(STATE["rows"], active)
        log_history(result)
        self._json(result)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", default="cache/quality_signals.json")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args()

    try:
        STATE["rows"] = load_rows(args.signals)
    except FileNotFoundError:
        sys.exit(f"{args.signals} not found -- run scripts/compute_quality_signals.py first")

    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"open http://<this-machine-ip>:{args.port}/  in a browser (Tailscale/LAN)")
    print(f"{len(STATE['rows'])} graded rallies loaded from {args.signals}")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
