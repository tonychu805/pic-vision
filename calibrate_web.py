#!/usr/bin/env python3
"""
Browser-based court calibration — same 12 court intersections + 2 net-tape
points as calibrate.py, but click them in a browser instead of a local X
window. For SSH sessions with no display: this starts a small local HTTP
server: open http://<this-machine's-ip>:<port>/ in a browser on your laptop
(works over Tailscale/LAN without any port forwarding) and click the points
directly on the frame image, with live markers and labels, just like the
original tool.

Usage:
    python calibrate_web.py session.mp4 --at 300 --out court_calibration.json --port 8765
"""
import argparse
import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2

from calibrate import POINTS, NET_PROMPTS, compute_calibration, solve_assignment

STATE = {}


def render_page():
    labels = [name for name, _ in POINTS] + list(NET_PROMPTS)
    labels_json = json.dumps(labels)
    n_court = len(POINTS)
    b64 = STATE["frame_b64"]
    w, h = STATE["frame_w"], STATE["frame_h"]
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>court calibration</title>
<style>
  body {{ margin: 0; background: #111; color: #eee; font-family: sans-serif; }}
  #bar {{ padding: 10px 14px; background: #1a1a1a; position: sticky; top: 0; }}
  #msg {{ font-size: 16px; }}
  #wrap {{ position: relative; display: inline-block; }}
  img {{ display: block; max-width: 100vw; height: auto; }}
  svg {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }}
  circle {{ fill: #0f0; }}
  circle.net {{ fill: #f33; }}
  text {{ fill: #ff0; font-size: 14px; font-weight: bold; }}
  button {{ font-size: 15px; padding: 6px 14px; margin-right: 8px; }}
  #status {{ margin-top: 6px; font-size: 13px; color: #aaa; }}
</style></head>
<body>
<div id="bar">
  <div id="msg">Click: <b id="label"></b></div>
  <div id="status"></div>
  <button onclick="undo()">Undo (u)</button>
  <button onclick="resetAll()">Reset (r)</button>
  <button id="save" onclick="save()" disabled>Save</button>
</div>
<div id="wrap">
  <img id="img" src="data:image/png;base64,{b64}">
  <svg id="ov" viewBox="0 0 {w} {h}"></svg>
</div>
<script>
const labels = {labels_json};
const nCourt = {n_court};
const total = labels.length;
let points = [];
const img = document.getElementById('img');
const ov = document.getElementById('ov');
const labelEl = document.getElementById('label');
const statusEl = document.getElementById('status');
const saveBtn = document.getElementById('save');

function render() {{
  labelEl.textContent = points.length < total ? labels[points.length] : "ALL PLACED - press Save";
  ov.innerHTML = '';
  points.forEach((p, i) => {{
    const net = i >= nCourt;
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', p[0]); c.setAttribute('cy', p[1]); c.setAttribute('r', 6);
    c.setAttribute('class', net ? 'net' : '');
    ov.appendChild(c);
    const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.setAttribute('x', p[0] + 9); t.setAttribute('y', p[1] - 9);
    t.textContent = net ? 'N' + (i - nCourt + 1) : String(i + 1);
    ov.appendChild(t);
  }});
  statusEl.textContent = points.length + ' / ' + total + ' placed';
  saveBtn.disabled = points.length !== total;
}}

img.addEventListener('click', (e) => {{
  if (points.length >= total) return;
  const r = img.getBoundingClientRect();
  const scale = {w} / r.width;
  const x = (e.clientX - r.left) * scale;
  const y = (e.clientY - r.top) * scale;
  points.push([x, y]);
  render();
}});

function undo() {{ points.pop(); render(); }}
function resetAll() {{ points = []; render(); }}

document.addEventListener('keydown', (e) => {{
  if (e.key === 'u') undo();
  if (e.key === 'r') resetAll();
}});

function save() {{
  fetch('/save', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{points}})
  }}).then(r => r.json()).then(d => {{
    if (d.error) {{ statusEl.textContent = 'ERROR: ' + d.error; return; }}
    statusEl.textContent = 'saved -> ' + d.out + '   RMSE = ' + d.rmse_ft.toFixed(3) + ' ft'
      + (d.rmse_ft > 0.5 ? '  (WARNING: re-check points, worst = ' + d.worst + ')' : '  (looks good)');
  }});
}}
render();
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        body = render_page().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/save":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length))
        points = data["points"]
        n_court = len(POINTS)
        court_points = [tuple(p) for p in points[:n_court]]
        net_points = [tuple(p) for p in points[n_court:]]

        try:
            ordered, _ = solve_assignment(court_points)
            result = compute_calibration(ordered)
        except Exception as e:
            self._json({"error": str(e)})
            return

        out = {
            "video": STATE["video"],
            "frame_at_sec": STATE["at"],
            **result,
            "net_image_points": [[float(x), float(y)] for x, y in net_points],
            "court_size_ft": [20.0, 44.0],
            "net_y_ft": 22.0,
        }
        with open(STATE["out"], "w") as f:
            json.dump(out, f, indent=2)

        err_ft = result["per_point_error_ft"]
        worst = int(max(range(len(err_ft)), key=lambda k: err_ft[k]))
        self._json({
            "out": STATE["out"],
            "rmse_ft": result["reprojection_rmse_ft"],
            "worst": POINTS[worst][0],
        })
        print(f"\nsaved {STATE['out']}  RMSE={result['reprojection_rmse_ft']:.3f}ft")
        STATE["saved"] = True

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--at", type=float, default=60.0,
                     help="seconds into the video to grab the frame")
    ap.add_argument("--out", default="court_calibration.json")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"could not read a frame at {args.at}s")

    ok, buf = cv2.imencode(".png", frame)
    STATE["frame_b64"] = base64.b64encode(buf.tobytes()).decode()
    STATE["frame_w"] = frame.shape[1]
    STATE["frame_h"] = frame.shape[0]
    STATE["video"] = args.video
    STATE["at"] = args.at
    STATE["out"] = args.out
    STATE["saved"] = False

    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"open http://<this-machine-ip>:{args.port}/  in a browser (e.g. your laptop, over Tailscale/LAN)")
    print("click the 12 court points then the 2 net-tape points; Save writes the JSON here on this machine.")
    print("Ctrl+C to stop once you see 'saved ...' above.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
