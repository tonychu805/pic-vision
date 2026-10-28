"""Tiny web review page for serve candidate clips (from cut_serve_clips.py).

Watch one clip at a time, mark serve / not_serve / wrong_side, verdicts save
straight back to the review.csv beside the clips. One-clip flow + keyboard
shortcuts so 37 clips go fast. Serve over Tailscale HTTPS (never raw IP/HTTP).

Usage: PYTHONPATH=. .venv/bin/python scripts/serve_review.py --dir cache/serve_review/far --port 8782
"""
import argparse, csv, html, json, os, pathlib, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default="cache/serve_review/far")
ap.add_argument("--port", type=int, default=8782)
args = ap.parse_args()

DIR = pathlib.Path(args.dir).resolve()
CSVP = DIR / "review.csv"
LOCK = threading.Lock()
VERDICTS = ["serve", "not_serve", "wrong_side"]


def load():
    with open(CSVP) as f:
        return list(csv.DictReader(f))


def save(rows):
    fields = list(rows[0].keys())
    tmp = CSVP.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    os.replace(tmp, CSVP)


PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Serve review</title>
<style>
 :root{color-scheme:dark}
 body{font:15px system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6;text-align:center}
 header{padding:8px;background:#171a21;border-bottom:1px solid #2a2f3a;font-size:13px;color:#9aa4b2}
 video{max-width:96vw;max-height:66vh;background:#000;margin:8px auto;display:block}
 .meta{color:#9aa4b2;font-size:13px;margin:4px}
 .big{font-size:17px;color:#e6e6e6}
 .btns{margin:10px}
 button{font-size:15px;padding:10px 16px;margin:4px;border-radius:8px;border:1px solid #2a2f3a;background:#1b212b;color:#e6e6e6;cursor:pointer}
 button:hover{background:#273040}
 .serve{border-color:#2e7d32}.not_serve{border-color:#b23b3b}.wrong_side{border-color:#b58b2a}
 .v-serve{color:#6fcf72}.v-not_serve{color:#ff8080}.v-wrong_side{color:#ffcf6b}
 .nav button{background:#121620}
 kbd{background:#2a2f3a;border-radius:4px;padding:1px 5px;font-size:12px}
</style>
<header>Serve review — <span id=prog></span> &nbsp;·&nbsp; <kbd>S</kbd> serve · <kbd>N</kbd> not · <kbd>W</kbd> wrong-side · <kbd>C</kbd> clear · <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> prev/next</header>
<div class=meta id=info></div>
<video id=vid controls autoplay loop></video>
<div class=big id=verdict></div>
<div class=btns>
 <button class=serve onclick="mark('serve')">Serve (S)</button>
 <button class=not_serve onclick="mark('not_serve')">Not a serve (N)</button>
 <button class=wrong_side onclick="mark('wrong_side')">Wrong side (W)</button>
 <button onclick="mark('')">Clear (C)</button>
</div>
<div class=btns nav><button onclick="go(-1)">&larr; Prev</button><button onclick="go(1)">Next &rarr;</button></div>
<script>
let rows=[], i=0;
async function boot(){ rows=await (await fetch('/manifest')).json();
  // start at first unlabelled
  let u=rows.findIndex(r=>!r.verdict); i=u<0?0:u; render(); }
function render(){ const r=rows[i];
  document.getElementById('vid').src='/clip/'+encodeURIComponent(r.clip)+'?t='+Date.now();
  document.getElementById('info').innerHTML=
    `#${r.idx} · ${r.name} · serve_t ${r.serve_t}s · court_y ${r.court_y} · swing ${r.swing_px_s}px/s · <span class=meta>${r.clip}</span>`;
  const v=r.verdict||'—';
  document.getElementById('verdict').innerHTML='verdict: <b class=v-'+(r.verdict||'')+'>'+v+'</b>';
  const done=rows.filter(x=>x.verdict).length;
  document.getElementById('prog').textContent=`${i+1}/${rows.length}  (${done} labelled)`;
}
async function mark(v){ const r=rows[i]; r.verdict=v;
  await fetch('/verdict',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({idx:r.idx,verdict:v})});
  render(); if(v) setTimeout(()=>go(1),150); }
function go(d){ i=Math.max(0,Math.min(rows.length-1,i+d)); render(); }
document.addEventListener('keydown',e=>{ if(e.target.tagName==='INPUT')return;
  const k=e.key.toLowerCase();
  if(k==='s')mark('serve'); else if(k==='n')mark('not_serve');
  else if(k==='w')mark('wrong_side'); else if(k==='c')mark('');
  else if(e.key==='ArrowLeft')go(-1); else if(e.key==='ArrowRight')go(1); });
boot();
</script>
"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, PAGE.encode())
        elif path == "/manifest":
            self._send(200, json.dumps(load()).encode(), "application/json")
        elif path.startswith("/clip/"):
            self._serve_clip(urllib_unquote(path[len("/clip/"):]))
        else:
            self._send(404, b"nope", "text/plain")

    def _serve_clip(self, name):
        if "/" in name or ".." in name:
            return self._send(400, b"bad", "text/plain")
        f = DIR / name
        if not f.exists():
            return self._send(404, b"no clip", "text/plain")
        size = f.stat().st_size
        rng = self.headers.get("Range")
        with open(f, "rb") as fh:
            if rng and (m := re.match(r"bytes=(\d+)-(\d*)", rng)):
                a = int(m.group(1)); b = int(m.group(2)) if m.group(2) else size - 1
                b = min(b, size - 1); fh.seek(a); data = fh.read(b - a + 1)
                self.send_response(206)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)
            else:
                data = fh.read()
                self._send(200, data, "video/mp4", {"Accept-Ranges": "bytes"})

    def do_POST(self):
        if self.path != "/verdict":
            return self._send(404, b"nope", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        with LOCK:
            rows = load()
            for r in rows:
                if r["idx"] == str(body.get("idx")):
                    r["verdict"] = body.get("verdict", "")
            save(rows)
        self._send(200, b'{"ok":true}', "application/json")


def urllib_unquote(s):
    import urllib.parse
    return urllib.parse.unquote(s)


if __name__ == "__main__":
    print(f"serving {DIR} ({len(load())} clips) on :{args.port}")
    print("expose via:  tailscale serve --bg --https <port> http://127.0.0.1:%d" % args.port)
    ThreadingHTTPServer(("0.0.0.0", args.port), H).serve_forever()
