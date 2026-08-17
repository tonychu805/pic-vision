#!/usr/bin/env python3
"""
Browser-based rally labeller — same two-pass workflow and same JSONL output as
label.py, but driven from a browser instead of a local X window. For SSH
sessions with no display (same rationale as calibrate_web.py): this starts a
small local HTTP server, you open it on your laptop, and the video streams to
the browser so decoding and playback happen there — only compressed video
crosses the network, unlike X11 forwarding which ships raw frames.

Two passes, as in label.py:
  MARK  — play through and mark serve -> ball-dead for every rally, no
          quality judgement (you can't judge at the serve).
  GRADE — replay each marked rally in isolation and grade it with hindsight:
          1 highlight-worthy, 2 real but ordinary, 3 not a rally (drops it).

Grades are written as a "quality" field (1 or 2). Detection metrics should
score against everything kept (real play); highlight-selection metrics against
grade 1 only. Grading down rather than deleting ordinary play is deliberate —
see LABELING.md and the 2026-08-09 curated-label mismatch.

Usage:
    python label_web.py videos/game.mp4 --out eval/labels/game.jsonl --port 8766
"""
import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from label import load_rallies, save_rallies

STATE = {}

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>rally labeller</title>
<style>
  :root { color-scheme: dark; }
  body { background:#111; color:#eee; font:14px/1.5 system-ui,sans-serif; margin:0; padding:16px;
         display:grid; grid-template-columns:1fr 340px; gap:16px; height:100vh; box-sizing:border-box; }
  video { width:100%; background:#000; border-radius:6px; }
  #side { overflow-y:auto; border-left:1px solid #333; padding-left:14px; }
  .bar { display:flex; gap:14px; align-items:center; margin:10px 0; flex-wrap:wrap; }
  .pill { background:#222; border:1px solid #444; border-radius:99px; padding:3px 12px; font-variant-numeric:tabular-nums; }
  .pending { background:#4a3000; border-color:#a70; }
  kbd { background:#222; border:1px solid #555; border-bottom-width:2px; border-radius:4px;
        padding:1px 6px; font-size:12px; }
  table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
  td { padding:3px 4px; border-bottom:1px solid #222; cursor:pointer; }
  tr:hover td { background:#1c1c1c; }
  tr.cur td { background:#093; color:#fff; }
  .q1 { color:#5f5; } .q2 { color:#fc5; } .none { color:#888; }
  button { background:#333; color:#eee; border:1px solid #555; border-radius:5px;
           padding:6px 12px; cursor:pointer; font-size:13px; }
  button:hover { background:#444; }
  #msg { color:#7d7; min-height:20px; }
  h3 { margin:14px 0 6px; font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:#999; }
  #help { color:#aaa; font-size:12px; }
  #help div { margin:3px 0; }
</style></head><body>
<div>
  <video id="v" src="/video" preload="metadata"></video>
  <div class="bar">
    <span class="pill" id="clock">00:00.00</span>
    <span class="pill" id="rate">1x</span>
    <span class="pill" id="state">idle</span>
    <span class="pill" id="mode">MARK</span>
    <span class="pill" id="count">0 rallies</span>
    <button onclick="save()">Save</button>
  </div>
  <div id="msg"></div>
  <div id="help">
    <div><b>MARK pass</b> &mdash; <kbd>space</kbd> play/pause &nbsp; <kbd>s</kbd> rally start (serve)
      &nbsp; <kbd>e</kbd> rally end (ball dead) &nbsp; <kbd>x</kbd> cancel start &nbsp; <kbd>u</kbd> undo last</div>
    <div><kbd>j</kbd>/<kbd>l</kbd> &plusmn;2s &nbsp; <kbd>J</kbd>/<kbd>L</kbd> &plusmn;10s
      &nbsp; <kbd>-</kbd>/<kbd>=</kbd> slower/faster &nbsp; <kbd>w</kbd> save</div>
    <div><b>GRADE pass</b> (<kbd>g</kbd> toggles) &mdash; replays each rally; <kbd>1</kbd> highlight
      &nbsp; <kbd>2</kbd> ordinary &nbsp; <kbd>3</kbd> not a rally &nbsp; <kbd>n</kbd>/<kbd>p</kbd> next/prev
      &nbsp; <kbd>space</kbd> replay</div>
  </div>
</div>
<div id="side">
  <h3>Rallies</h3>
  <table id="list"></table>
</div>
<script>
const v = document.getElementById('v');
let rallies = INITIAL_RALLIES;
let pending = null, mode = 'MARK', cur = 0, rate = 1;
// Undo must remove the most recently *added* rally, which is not the last array
// element — the list is kept sorted by start time, so marking one after seeking
// back would otherwise undo the wrong rally.
let undoStack = [];

const fmt = t => {
  const m = Math.floor(t/60), s = t%60;
  return String(m).padStart(2,'0') + ':' + s.toFixed(2).padStart(5,'0');
};
const msg = t => { document.getElementById('msg').textContent = t; };

function render() {
  document.getElementById('count').textContent = rallies.length + ' rallies';
  document.getElementById('mode').textContent = mode;
  document.getElementById('state').textContent =
    pending === null ? 'idle' : 'START @ ' + fmt(pending);
  document.getElementById('state').className = 'pill' + (pending === null ? '' : ' pending');
  const rows = rallies.map((r,i) => {
    const q = r.quality === 1 ? '<span class="q1">1 highlight</span>'
            : r.quality === 2 ? '<span class="q2">2 ordinary</span>'
            : '<span class="none">&mdash;</span>';
    const cls = (mode === 'GRADE' && i === cur) ? ' class="cur"' : '';
    return `<tr${cls} onclick="jump(${i})"><td>${i+1}</td><td>${fmt(r.start)}</td>` +
           `<td>${(r.end-r.start).toFixed(1)}s</td><td>${q}</td></tr>`;
  }).join('');
  document.getElementById('list').innerHTML = rows;
  const el = document.querySelector('tr.cur');
  if (el) el.scrollIntoView({block:'nearest'});
}

function jump(i) {
  cur = i;
  v.currentTime = rallies[i].start;
  render();
}

// GRADE pass: loop playback inside the current rally so it can be judged whole.
v.addEventListener('timeupdate', () => {
  document.getElementById('clock').textContent = fmt(v.currentTime);
  if (mode === 'GRADE' && rallies[cur] && v.currentTime >= rallies[cur].end) {
    v.currentTime = rallies[cur].start;
  }
});

function setRate(r) {
  rate = Math.min(8, Math.max(0.25, r));
  v.playbackRate = rate;
  document.getElementById('rate').textContent = rate + 'x';
}

function grade(q) {
  if (!rallies[cur]) return;
  if (q === 3) {
    msg('dropped rally ' + (cur+1) + ' (not a rally)');
    rallies.splice(cur, 1);
    if (cur >= rallies.length) cur = Math.max(0, rallies.length - 1);
  } else {
    rallies[cur].quality = q;
    msg('rally ' + (cur+1) + ' graded ' + q);
    cur = Math.min(cur + 1, rallies.length - 1);
  }
  if (rallies[cur]) v.currentTime = rallies[cur].start;
  render();
}

document.addEventListener('keydown', ev => {
  if (ev.target.tagName === 'INPUT') return;
  const k = ev.key;
  if (k === ' ') {
    ev.preventDefault();
    if (mode === 'GRADE' && rallies[cur]) v.currentTime = rallies[cur].start;
    v.paused ? v.play() : v.pause();
    return;
  }
  if (k === 'g') {
    mode = mode === 'MARK' ? 'GRADE' : 'MARK';
    if (mode === 'GRADE' && rallies.length) { cur = 0; v.currentTime = rallies[0].start; v.play(); }
    msg(mode === 'GRADE' ? 'GRADE pass — judge each rally after watching it'
                         : 'MARK pass — mark every rally, no judgement');
    render(); return;
  }
  if (mode === 'GRADE') {
    if (k === '1' || k === '2' || k === '3') { grade(+k); return; }
    if (k === 'n') { cur = Math.min(cur+1, rallies.length-1); v.currentTime = rallies[cur].start; render(); return; }
    if (k === 'p') { cur = Math.max(cur-1, 0); v.currentTime = rallies[cur].start; render(); return; }
  } else {
    if (k === 's') { pending = v.currentTime; msg('start ' + fmt(pending)); render(); return; }
    if (k === 'e') {
      if (pending === null) { msg('! no pending start'); return; }
      if (v.currentTime <= pending) { msg('! end before start, ignored'); return; }
      const r = {start:+pending.toFixed(2), end:+v.currentTime.toFixed(2),
                 duration:+(v.currentTime-pending).toFixed(2)};
      rallies.push(r);
      undoStack.push(r);
      rallies.sort((a,b) => a.start - b.start);
      msg('rally ' + rallies.length + ': ' + fmt(pending) + ' -> ' + fmt(v.currentTime));
      pending = null; render(); return;
    }
    if (k === 'x') { pending = null; msg('cancelled'); render(); return; }
    if (k === 'u') {
      const r = undoStack.pop();
      if (!r) { msg('nothing to undo'); return; }
      const i = rallies.indexOf(r);
      if (i >= 0) rallies.splice(i, 1);
      msg('undid ' + fmt(r.start)); render(); return;
    }
  }
  if (k === 'j') v.currentTime -= 2;
  else if (k === 'l') v.currentTime += 2;
  else if (k === 'J') v.currentTime -= 10;
  else if (k === 'L') v.currentTime += 10;
  else if (k === '-') setRate(rate / 2);
  else if (k === '=' || k === '+') setRate(rate * 2);
  else if (k === 'w') save();
});

async function save() {
  const r = await fetch('/save', {method:'POST', body: JSON.stringify(rallies)});
  const j = await r.json();
  msg('saved ' + j.n + ' rallies -> ' + j.out + '  (' + j.q1 + ' highlight, ' + j.q2 + ' ordinary)');
}
setRate(2);
render();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            body = PAGE.replace("INITIAL_RALLIES",
                                json.dumps(STATE["rallies"])).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/video":
            self._serve_video()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_video(self):
        """Serve the video with HTTP range support — browsers require it to seek."""
        path = STATE["video"]
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
        end = min(end, size - 1)
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return          # browser seeked away; not an error
                remaining -= len(chunk)

    def do_POST(self):
        if self.path != "/save":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        rallies = json.loads(self.rfile.read(length))
        save_rallies(rallies, STATE["out"])
        STATE["rallies"] = rallies
        q1 = sum(1 for r in rallies if r.get("quality") == 1)
        q2 = sum(1 for r in rallies if r.get("quality") == 2)
        body = json.dumps({"n": len(rallies), "out": STATE["out"],
                           "q1": q1, "q2": q2}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(f"saved {len(rallies)} rallies -> {STATE['out']} "
              f"({q1} highlight, {q2} ordinary)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="mp4 the browser can play (H.264; .MOV/HEVC may not decode)")
    ap.add_argument("--out", required=True, help="labels .jsonl (read on start, written on save)")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit(f"no such video: {args.video}")

    STATE["video"] = args.video
    STATE["out"] = args.out
    STATE["rallies"] = load_rallies(args.out)
    if STATE["rallies"]:
        print(f"resuming — {len(STATE['rallies'])} rallies already labelled")

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.daemon_threads = True
    print(f"open http://<this-machine-ip>:{args.port}/  in a browser on your laptop "
          f"(works over Tailscale/LAN)")
    print("MARK pass: s = serve, e = ball dead. Press g for the GRADE pass. w saves.")
    print("Ctrl+C to stop (save first — nothing is written until you save).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
