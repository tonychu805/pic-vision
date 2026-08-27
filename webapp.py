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
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler

from webapp.app import app

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_FILE = os.path.join(REPO_ROOT, "webapp", "webapp.log")


def _configure_logging(log_file, log_level):
    # Attaches to the *root* logger deliberately, not a module-local one --
    # Werkzeug's request logging and Flask's own error logging already go
    # through logging.getLogger('werkzeug')/app.logger, both of which
    # propagate to root by default, so this captures them for free.
    root = logging.getLogger()
    root.setLevel(log_level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s",
                             datefmt="%Y-%m-%d %H:%M:%S")
    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(fmt)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def _install_signal_logging():
    # A prior run was killed by SIGHUP when its launching terminal closed,
    # leaving zero trace anywhere (checked dmesg/journalctl -- nothing).
    # Logging the signal before exiting is what would have made that
    # visible after the fact; it doesn't prevent the kill (that's process
    # supervision, a separate concern), just makes it stop being silent.
    log = logging.getLogger("webapp")

    def _handle(signum, _frame):
        log.warning("received %s, shutting down", signal.Signals(signum).name)
        sys.exit(0)

    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _handle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8801)
    ap.add_argument("--log-file", default=DEFAULT_LOG_FILE)
    ap.add_argument("--log-level", default="INFO",
                     choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args()
    _configure_logging(args.log_file, args.log_level)
    _install_signal_logging()
    logging.getLogger("webapp").info("starting on %s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
