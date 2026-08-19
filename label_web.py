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
          A candidate's start/end can also be wrong without the candidate
          itself being wrong (e.g. pass-3 gap review: a detector segment
          spans only first-to-last net crossing, not serve-to-dead). Press
          s/e in GRADE to re-mark the true boundary in place -- the original
          pipeline timestamp is kept alongside it as detector_start/
          detector_end, not discarded, so this never needs a second,
          detached hand-marked entry for the same candidate. 0 reverts to
          the pipeline boundary.

Grades are written as a "quality" field (1 or 2). Detection metrics should
score against everything kept (real play); highlight-selection metrics against
grade 1 only. Grading down rather than deleting ordinary play is deliberate —
see LABELING.md and the 2026-08-09 curated-label mismatch.

Usage:
    python label_web.py                     # pick a video in the browser
    python label_web.py videos/game.mp4     # straight to one video (labels derived)
    python label_web.py videos/game.mp4 --out eval/labels/game.jsonl --port 8766

With no video argument it lists the playable videos in --video-dir and shows how
many rallies each already has, so a session can be resumed without remembering
paths. Labels follow the project convention videos/<stem>.mp4 ->
eval/labels/<stem>.jsonl; --out still overrides it for a one-off.
"""
import argparse
import json
import os
import re
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlparse, parse_qs

from label import load_rallies, save_rallies

# Browsers cannot decode HEVC .MOV (see module docstring), and videos/raw/ holds
# exactly those originals -- offering them in the picker would just produce a
# black player, so discovery is deliberately top-level and extension-filtered.
PLAYABLE = (".mp4", ".m4v", ".webm")


def labels_path_for(video_path, labels_dir):
    """The project convention: videos/<stem>.mp4 -> <labels_dir>/<stem>.jsonl."""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    return os.path.join(labels_dir, stem + ".jsonl")


def discover_videos(video_dir, labels_dir):
    """Playable videos in video_dir (not recursive), each with its label count.

    A video with no label file reports 0 rather than being hidden -- starting a
    fresh video is the normal case, not an error."""
    try:
        names = sorted(os.listdir(video_dir))
    except FileNotFoundError:
        return []
    out = []
    for name in names:
        path = os.path.join(video_dir, name)
        if not os.path.isfile(path) or not name.lower().endswith(PLAYABLE):
            continue
        lp = labels_path_for(path, labels_dir)
        rallies = load_rallies(lp)
        out.append({
            "name": name,
            "path": path,
            "labels": lp,
            "n_labels": len(rallies),
            "n_graded": sum(1 for r in rallies if r.get("quality")),
            "size_mb": os.path.getsize(path) / (1 << 20),
        })
    return out


def resolve_selection(name, videos):
    """Map a name sent by the browser back to a discovered video, or None.

    The picker round-trips this name through the client, so matching only against
    already-discovered entries is what stops '../../etc/passwd' being opened."""
    for v in videos:
        if v["name"] == name:
            return v
    return None


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
  .dim { color:#888; font-size:11px; }
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
    NAV_LINK
  </div>
  <div id="msg">NOW_LABELLING</div>
  <div id="help">
    <div><b>MARK pass</b> &mdash; <kbd>space</kbd> play/pause &nbsp; <kbd>s</kbd> rally start (serve)
      &nbsp; <kbd>e</kbd> rally end (ball dead) &nbsp; <kbd>x</kbd> cancel start &nbsp; <kbd>u</kbd> undo last</div>
    <div><kbd>j</kbd>/<kbd>l</kbd> &plusmn;2s &nbsp; <kbd>J</kbd>/<kbd>L</kbd> &plusmn;10s
      &nbsp; <kbd>-</kbd>/<kbd>=</kbd> slower/faster &nbsp; <kbd>w</kbd> save</div>
    <div><b>GRADE pass</b> (<kbd>g</kbd> toggles) &mdash; replays each rally; <kbd>1</kbd> highlight
      &nbsp; <kbd>2</kbd> ordinary &nbsp; <kbd>3</kbd> not a rally &nbsp; <kbd>n</kbd>/<kbd>p</kbd> next/prev
      &nbsp; <kbd>space</kbd> replay</div>
    <div><b>Boundary correction</b> (in GRADE) &mdash; <kbd>s</kbd> re-mark start here &nbsp;
      <kbd>e</kbd> re-mark end here (unlocks looping to seek past the old edges) &nbsp;
      <kbd>0</kbd> revert to pipeline boundary &nbsp; <kbd>x</kbd> cancel pending</div>
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
    const corrected = r.detector_start !== undefined
      ? ' <span class="dim" title="pipeline: ' + fmt(r.detector_start) + ' -> ' + fmt(r.detector_end) + '">*corrected</span>'
      : '';
    return `<tr${cls} onclick="jump(${i})"><td>${i+1}</td><td>${fmt(r.start)}</td>` +
           `<td>${(r.end-r.start).toFixed(1)}s${corrected}</td><td>${q}</td></tr>`;
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
// Suspended while a boundary correction is pending (pending !== null) so the
// old edge doesn't snap playback back before the true edge can be found.
v.addEventListener('timeupdate', () => {
  document.getElementById('clock').textContent = fmt(v.currentTime);
  if (mode === 'GRADE' && rallies[cur] && pending === null && v.currentTime >= rallies[cur].end) {
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
    if (mode === 'GRADE' && rallies[cur] && pending === null) v.currentTime = rallies[cur].start;
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
    // Re-mark this candidate's boundary in place. The pipeline's original
    // start/end is snapshotted once into detector_start/detector_end (never
    // overwritten again) so both timestamps survive -- correcting a boundary
    // never requires a second, detached hand-marked entry for the same rally.
    if (k === 's') {
      if (!rallies[cur]) return;
      pending = v.currentTime;
      msg('corrected start @ ' + fmt(pending) + ' -- seek to the true end, then press e');
      render(); return;
    }
    if (k === 'e') {
      if (!rallies[cur]) return;
      if (pending === null) { msg('! no pending corrected start -- press s first'); return; }
      if (v.currentTime <= pending) { msg('! end before start, ignored'); return; }
      const r = rallies[cur];
      if (r.detector_start === undefined) { r.detector_start = r.start; r.detector_end = r.end; }
      r.start = +pending.toFixed(2);
      r.end = +v.currentTime.toFixed(2);
      r.duration = +(r.end - r.start).toFixed(2);
      pending = null;
      msg('rally ' + (cur+1) + ' boundary corrected: ' + fmt(r.start) + ' -> ' + fmt(r.end) +
          '  (pipeline was ' + fmt(r.detector_start) + ' -> ' + fmt(r.detector_end) + ')');
      render(); return;
    }
    if (k === '0') {
      const r = rallies[cur];
      if (!r || r.detector_start === undefined) { msg('no correction to revert'); return; }
      r.start = r.detector_start; r.end = r.detector_end;
      r.duration = +(r.end - r.start).toFixed(2);
      msg('rally ' + (cur+1) + ' reverted to pipeline boundary');
      render(); return;
    }
    if (k === 'x') { pending = null; msg('cancelled pending correction'); render(); return; }
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


PICKER = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>pick a video</title>
<style>
  :root { color-scheme: dark; }
  body { background:#111; color:#eee; font:14px/1.6 system-ui,sans-serif; margin:0; padding:28px; }
  h1 { font-size:18px; margin:0 0 4px; }
  p.sub { color:#888; margin:0 0 22px; font-size:13px; }
  table { border-collapse:collapse; width:100%; max-width:820px; font-variant-numeric:tabular-nums; }
  th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.08em;
       color:#888; border-bottom:1px solid #333; padding:6px 10px; font-weight:600; }
  td { padding:10px; border-bottom:1px solid #222; }
  tr.row:hover td { background:#1b1b1b; }
  a.name { color:#7cf; text-decoration:none; font-weight:600; }
  a.name:hover { text-decoration:underline; }
  .badge { border-radius:99px; padding:2px 10px; font-size:12px; border:1px solid #444; background:#222; }
  .resume { background:#093; border-color:#0b4; color:#fff; }
  .fresh { color:#888; }
  .dim { color:#777; font-size:12px; }
  .empty { color:#c96; }
</style></head><body>
<h1>Rally labeller</h1>
<p class="sub">VIDEO_DIR &rarr; labels in LABELS_DIR. Pick a video to start or resume.</p>
<table>
  <tr><th>video</th><th>size</th><th>labels</th><th>status</th></tr>
  ROWS
</table>
</body></html>
"""


def render_picker(videos, video_dir, labels_dir):
    if not videos:
        rows = ('<tr><td colspan="4" class="empty">No playable videos in this folder. '
                'Browsers cannot decode .MOV/HEVC — convert to .mp4 first.</td></tr>')
    else:
        rows = []
        for v in videos:
            if v["n_labels"]:
                status = f'<span class="badge resume">resume &middot; {v["n_graded"]} graded</span>'
                labels = f'{v["n_labels"]}'
            else:
                status = '<span class="badge fresh">not started</span>'
                labels = '<span class="dim">&mdash;</span>'
            rows.append(
                f'<tr class="row"><td><a class="name" href="/label?v={quote(v["name"])}">'
                f'{escape(v["name"])}</a><div class="dim">{escape(v["labels"])}</div></td>'
                f'<td class="dim">{v["size_mb"]:.0f} MB</td>'
                f'<td>{labels}</td><td>{status}</td></tr>')
        rows = "\n  ".join(rows)
    return (PICKER.replace("ROWS", rows)
                  .replace("VIDEO_DIR", escape(video_dir))
                  .replace("LABELS_DIR", escape(labels_dir)))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        route = urlparse(self.path)
        if route.path == "/" and STATE.get("picker"):
            self._send_html(render_picker(
                discover_videos(STATE["video_dir"], STATE["labels_dir"]),
                STATE["video_dir"], STATE["labels_dir"]))
        elif route.path == "/label" and STATE.get("picker"):
            want = (parse_qs(route.query).get("v") or [""])[0]
            chosen = resolve_selection(
                want, discover_videos(STATE["video_dir"], STATE["labels_dir"]))
            if chosen is None:
                self.send_response(404)
                self.end_headers()
                return
            STATE["video"] = chosen["path"]
            STATE["out"] = chosen["labels"]
            STATE["rallies"] = load_rallies(chosen["labels"])
            print(f"labelling {chosen['name']} -> {chosen['labels']} "
                  f"({len(STATE['rallies'])} existing)")
            self._send_html(self._labeller_page())
        elif route.path == "/":
            self._send_html(self._labeller_page())
        elif route.path == "/video":
            if not STATE.get("video"):
                self.send_response(409)
                self.end_headers()
                return
            self._serve_video()
        else:
            self.send_response(404)
            self.end_headers()

    def _send_html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _labeller_page(self):
        nav = ('<button onclick="location.href=\'/\'">&larr; videos</button>'
               if STATE.get("picker") else "")
        return (PAGE.replace("INITIAL_RALLIES", json.dumps(STATE["rallies"]))
                    .replace("NAV_LINK", nav)
                    .replace("NOW_LABELLING",
                             escape(os.path.basename(STATE["video"])) + " &rarr; "
                             + escape(STATE["out"])))

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
    ap.add_argument("video", nargs="?",
                    help="mp4 the browser can play (H.264; .MOV/HEVC may not decode). "
                         "Omit to pick one in the browser.")
    ap.add_argument("--out", help="labels .jsonl (read on start, written on save). "
                                  "Defaults to <labels-dir>/<video stem>.jsonl")
    ap.add_argument("--video-dir", default="videos",
                    help="folder the picker lists (default: videos)")
    ap.add_argument("--labels-dir", default="eval/labels",
                    help="where labels live (default: eval/labels)")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args()

    STATE["video_dir"] = args.video_dir
    STATE["labels_dir"] = args.labels_dir
    STATE["picker"] = args.video is None

    if args.video is None:
        found = discover_videos(args.video_dir, args.labels_dir)
        if not found:
            sys.exit(f"no playable videos in {args.video_dir}/ "
                     f"(browsers can't decode .MOV/HEVC — convert to .mp4 first)")
        print(f"{len(found)} video(s) in {args.video_dir}/:")
        for v in found:
            state = f"{v['n_labels']} labels" if v["n_labels"] else "not started"
            print(f"  {v['name']:<44} {state}")
    else:
        if not os.path.exists(args.video):
            sys.exit(f"no such video: {args.video}")
        STATE["video"] = args.video
        STATE["out"] = args.out or labels_path_for(args.video, args.labels_dir)
        STATE["rallies"] = load_rallies(STATE["out"])
        print(f"labelling {args.video} -> {STATE['out']}")
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
