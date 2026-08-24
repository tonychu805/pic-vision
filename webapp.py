#!/usr/bin/env python3
"""Launcher for the pic-vision web UI: upload footage, calibrate, let the
pipeline run, then preview and download the reel -- the same sequence this
project has run manually all along, wrapped in a browser instead of a
terminal. Purely additive: every existing CLI tool (calibrate_web.py,
scripts/check_drift.py, scripts/pod_infer.py, scripts/rank_and_reel.py)
keeps working standalone, untouched by this app.

Usage:
    python3 webapp.py --port 8801
Then open http://<this-machine-ip>:8801/ in a browser (works over
Tailscale/LAN without any port forwarding, same as calibrate_web.py).
"""
import argparse

from webapp.app import app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8801)
    args = ap.parse_args()
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
