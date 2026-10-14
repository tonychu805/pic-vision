#!/usr/bin/env python3
"""
Browser tool for marking where the ball bounces (bounce-labelling pilot, 2026-10-14).

For each clip in eval/labels/bounces/sample.json you step through the rally one frame
at a time and click the spot on the floor where the ball touches down. The server
decodes the clip with OpenCV and sends exact frames as JPEGs, because a browser's own
video seeking is not frame-accurate and cannot play HEVC.

Blind on purpose: no detector output is shown, so the labels can be used to measure
how much of the real play the detector sees. Marks are saved after every change to
eval/labels/bounces/labels.jsonl (one row per clip).

Keys:   left / right  step one frame      shift+left / right  step five frames
        space         play / pause (slow)  click   mark a bounce on this frame
        shift+click   mark a bounce where the ball is NOT visible (you can tell it landed)
        backspace     remove the mark on this frame      c  toggle "all bounces marked"
        n / p         next / previous clip

Usage:  python label_bounce_web.py [--port 8767] [--host 127.0.0.1]
Open it through `tailscale serve` (HTTPS hostname), not the raw IP.
"""
import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2

SAMPLE = "eval/labels/bounces/sample.json"
LABELS = "eval/labels/bounces/labels.jsonl"
PAD_SEC = 1.0
MAX_W = 1280
LOCK = threading.Lock()
CACHE = {}   # clip id -> {"fps", "first", "w", "h", "scale", "jpegs": [bytes]}


def load_sample(path=SAMPLE):
    return {c["id"]: c for c in json.load(open(path))["clips"]}


def load_labels(path=LABELS):
    if not os.path.exists(path):
        return {}
    return {r["clip"]: r for r in (json.loads(l) for l in open(path) if l.strip())}


def save_labels(rows, path=LABELS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for cid in sorted(rows):
            f.write(json.dumps(rows[cid]) + "\n")
    os.replace(tmp, path)


def decode_clip(clip):
    """Frames of the clip, padded by PAD_SEC each side, as JPEGs at <= MAX_W wide."""
    cap = cv2.VideoCapture(clip["video"])
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    first = max(0, int((clip["start"] - PAD_SEC) * fps))
    last = int((clip["end"] + PAD_SEC) * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    jpegs, w0, h0 = [], 0, 0
    for _ in range(first, last + 1):
        ok, img = cap.read()
        if not ok:
            break
        h0, w0 = img.shape[:2]
        scale = min(1.0, MAX_W / w0)
        if scale < 1.0:
            img = cv2.resize(img, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
        jpegs.append(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes())
    cap.release()
    return {"fps": fps, "first": first, "w": w0, "h": h0, "scale": min(1.0, MAX_W / w0) if w0 else 1.0,
            "jpegs": jpegs}


def get_clip(cid, sample):
    with LOCK:
        if cid not in CACHE:
            CACHE.clear()          # one clip in memory at a time
            CACHE[cid] = decode_clip(sample[cid])
        return CACHE[cid]


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>bounce labeller</title>
<style>:root{color-scheme:dark}body{background:#111;color:#eee;font:14px system-ui;margin:0;padding:12px}
canvas{background:#000;border-radius:6px;max-width:100%;cursor:crosshair}
.pill{background:#222;border:1px solid #444;border-radius:99px;padding:3px 12px;margin-right:8px;font-variant-numeric:tabular-nums}
.ok{background:#063;border-color:#0a5}button{background:#333;color:#eee;border:1px solid #555;border-radius:5px;padding:6px 12px;margin-right:6px;cursor:pointer}
#list{margin-top:10px;color:#aaa;font-size:12px}</style></head><body>
<div id="top"></div><canvas id="c"></canvas><div id="bar" style="margin:8px 0"></div><div id="list"></div>
<script>
const CLIPS = __CLIPS__;
let ci = 0, meta = null, imgs = [], cur = 0, marks = [], complete = false, playing = null, timer = null;
const c = document.getElementById('c'), g = c.getContext('2d');
async function openClip(i) {
  ci = i; const id = CLIPS[i].id; document.getElementById('top').innerHTML = 'loading ' + id + ' ...';
  meta = await (await fetch('/meta?clip=' + id)).json();
  imgs = await Promise.all(Array.from({length: meta.n}, (_, k) => new Promise(r => { const im = new Image(); im.onload = () => r(im); im.src = '/frame?clip=' + id + '&i=' + k; })));
  const lab = meta.label || {bounces: [], complete: false};
  marks = lab.bounces; complete = lab.complete; cur = 0; c.width = imgs[0].width; c.height = imgs[0].height; draw();
}
function draw() {
  g.drawImage(imgs[cur], 0, 0);
  const here = marks.filter(m => m.frame === meta.first + cur);
  marks.forEach(m => { const d = m.frame - (meta.first + cur); if (Math.abs(d) > 0 && Math.abs(d) <= 6) { g.strokeStyle = 'rgba(255,200,0,.5)'; g.beginPath(); g.arc(m.x * meta.scale, m.y * meta.scale, 5, 0, 7); g.stroke(); } });
  here.forEach(m => { g.strokeStyle = m.visible ? '#0f0' : '#f0f'; g.lineWidth = 2; g.beginPath(); g.arc(m.x * meta.scale, m.y * meta.scale, 9, 0, 7); g.stroke(); });
  const id = CLIPS[ci].id;
  document.getElementById('top').innerHTML = `<span class="pill">${ci + 1}/${CLIPS.length}</span><span class="pill">${id} (${CLIPS[ci].set})</span><span class="pill">frame ${meta.first + cur} (${cur + 1}/${meta.n})</span><span class="pill ${complete ? 'ok' : ''}">${marks.length} bounces ${complete ? '- complete' : ''}</span>`;
  document.getElementById('list').textContent = 'marks: ' + marks.slice().sort((a, b) => a.frame - b.frame).map(m => m.frame + (m.visible ? '' : '*')).join(', ');
}
async function save() { await fetch('/save', {method: 'POST', body: JSON.stringify({clip: CLIPS[ci].id, bounces: marks, complete})}); }
c.addEventListener('click', e => {
  const r = c.getBoundingClientRect(), sx = c.width / r.width;
  const x = (e.clientX - r.left) * sx / meta.scale, y = (e.clientY - r.top) * sx / meta.scale;
  marks = marks.filter(m => m.frame !== meta.first + cur);
  marks.push({frame: meta.first + cur, t: (meta.first + cur) / meta.fps, x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, visible: !e.shiftKey});
  draw(); save();
});
addEventListener('keydown', e => {
  if (!meta) return;
  const step = d => { cur = Math.max(0, Math.min(meta.n - 1, cur + d)); draw(); };
  if (e.key === 'ArrowRight') step(e.shiftKey ? 5 : 1); else if (e.key === 'ArrowLeft') step(e.shiftKey ? -5 : -1);
  else if (e.key === ' ') { e.preventDefault(); if (timer) { clearInterval(timer); timer = null; } else timer = setInterval(() => { if (cur < meta.n - 1) step(1); else { clearInterval(timer); timer = null; } }, 130); }
  else if (e.key === 'Backspace') { marks = marks.filter(m => m.frame !== meta.first + cur); draw(); save(); }
  else if (e.key === 'c') { complete = !complete; draw(); save(); }
  else if (e.key === 'n' && ci < CLIPS.length - 1) openClip(ci + 1); else if (e.key === 'p' && ci > 0) openClip(ci - 1);
});
openClip(0);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(route.query).items()}
        sample = self.server.sample
        if route.path == "/":
            clips = [{"id": c["id"], "set": c["set"]} for c in sample.values()]
            self._send(PAGE.replace("__CLIPS__", json.dumps(clips)).encode(), "text/html; charset=utf-8")
        elif route.path in ("/meta", "/frame") and q.get("clip") in sample:
            clip = get_clip(q["clip"], sample)
            if route.path == "/meta":
                lab = load_labels().get(q["clip"])
                body = json.dumps({"fps": clip["fps"], "first": clip["first"], "n": len(clip["jpegs"]),
                                   "scale": clip["scale"], "label": lab}).encode()
                self._send(body, "application/json")
            else:
                i = int(q.get("i", 0))
                if 0 <= i < len(clip["jpegs"]):
                    self._send(clip["jpegs"][i], "image/jpeg")
                else:
                    self._send(b"", "text/plain", 404)
        else:
            self._send(b"", "text/plain", 404)

    def do_POST(self):
        if self.path != "/save":
            return self._send(b"", "text/plain", 404)
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        sample = self.server.sample
        if data.get("clip") not in sample:
            return self._send(b"", "text/plain", 404)
        with LOCK:
            rows = load_labels()
            c = sample[data["clip"]]
            rows[data["clip"]] = {"clip": data["clip"], "set": c["set"], "video": c["video"],
                                  "start": c["start"], "end": c["end"],
                                  "complete": bool(data.get("complete")),
                                  "bounces": sorted(data.get("bounces", []), key=lambda b: b["frame"])}
            save_labels(rows)
        self._send(b"{}", "application/json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.sample = load_sample()
    print(f"bounce labeller on http://{args.host}:{args.port}  ({len(server.sample)} clips) -> {LABELS}")
    server.serve_forever()


if __name__ == "__main__":
    main()
