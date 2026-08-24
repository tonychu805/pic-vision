"""Flask routes for the pic-vision web UI: upload footage, calibrate the
court (reusing calibrate.py's click-collection logic), let the pipeline run
in the background, then preview and download the reel.

Purely additive -- every existing CLI tool (calibrate_web.py,
scripts/check_drift.py, scripts/pod_infer.py, scripts/rank_and_reel.py)
keeps working standalone, untouched by this app.
"""
import base64
import json
import os
import secrets
import sys
import threading
import time

import cv2
import yaml
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from calibrate import POINTS, NET_PROMPTS, compute_calibration, solve_assignment
from webapp import pipeline

JOBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

with open(os.path.join(REPO_ROOT, "config.yaml")) as f:
    _CONFIG = yaml.safe_load(f)
DEFAULT_TARGET_SEC = _CONFIG["output"]["highlight_budget_sec"]

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".avi", ".MP4", ".MOV", ".MKV", ".AVI"}

app = Flask(__name__)

_lock = threading.Lock()
_active_job = {"id": None}


def _job_dir(job_id):
    path = os.path.join(JOBS_DIR, job_id)
    if not os.path.isdir(path):
        abort(404)
    return path


def _read_status(job_dir):
    path = os.path.join(job_dir, "status.json")
    if not os.path.exists(path):
        return {"stage": "uploaded", "message": "waiting for calibration", "done": False}
    with open(path) as f:
        return json.load(f)


def _job_busy():
    with _lock:
        jid = _active_job["id"]
    if jid is None:
        return False
    return not _read_status(os.path.join(JOBS_DIR, jid)).get("done", False)


@app.route("/")
def index():
    return render_template("upload.html", busy=_job_busy(),
                           default_target_sec=int(DEFAULT_TARGET_SEC))


@app.route("/upload", methods=["POST"])
def upload():
    if _job_busy():
        return "a job is already running -- wait for it to finish first", 409
    f = request.files.get("video")
    if not f or not f.filename:
        return redirect(url_for("index"))
    ext = os.path.splitext(f.filename)[1]
    if ext not in ALLOWED_EXT:
        return f"unsupported file type {ext}", 400
    target_sec = float(request.form.get("target_sec") or DEFAULT_TARGET_SEC)

    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir)
    video_file = "video_original" + ext
    f.save(os.path.join(job_dir, video_file))

    with open(os.path.join(job_dir, "job.json"), "w") as jf:
        json.dump({"video_file": video_file, "target_sec": target_sec,
                   "session_id": job_id}, jf, indent=2)

    return redirect(url_for("calibrate_page", job_id=job_id))


def _grab_frame(video_path, at_sec):
    """Returns (base64_png or None, duration_sec)."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = n_frames / fps if fps else 0.0
    cap.set(cv2.CAP_PROP_POS_MSEC, at_sec * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None, duration
    ok, buf = cv2.imencode(".png", frame)
    return base64.b64encode(buf.tobytes()).decode(), duration


@app.route("/job/<job_id>/calibrate")
def calibrate_page(job_id):
    job_dir = _job_dir(job_id)
    with open(os.path.join(job_dir, "job.json")) as f:
        job = json.load(f)
    video_path = os.path.join(job_dir, job["video_file"])

    _, probe_duration = _grab_frame(video_path, 0.0)
    default_at = round(probe_duration * 0.10, 1) if probe_duration else 10.0
    at = float(request.args.get("at", default_at))

    frame_b64, duration = _grab_frame(video_path, at)
    if frame_b64 is None:
        return f"could not read a frame at {at}s (video is {duration:.0f}s long)", 400

    cap = cv2.VideoCapture(video_path)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    labels = [name for name, _ in POINTS] + list(NET_PROMPTS)
    return render_template("calibrate.html", job_id=job_id, frame_b64=frame_b64,
                           w=w, h=h, labels=json.dumps(labels), n_court=len(POINTS),
                           at=at, duration_int=int(round(duration)))


@app.route("/job/<job_id>/calibrate/save", methods=["POST"])
def calibrate_save(job_id):
    if _job_busy():
        return jsonify({"error": "a job is already running"}), 409
    job_dir = _job_dir(job_id)
    data = request.get_json()
    points = data["points"]
    n_court = len(POINTS)
    if len(points) != n_court + len(NET_PROMPTS):
        return jsonify({"error": f"expected {n_court + len(NET_PROMPTS)} points, "
                                  f"got {len(points)}"}), 400
    court_points = [tuple(p) for p in points[:n_court]]
    net_points = [tuple(p) for p in points[n_court:]]

    try:
        ordered, _ = solve_assignment(court_points)
        result = compute_calibration(ordered)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    with open(os.path.join(job_dir, "job.json")) as f:
        job = json.load(f)

    calib = {
        "video": job["video_file"],
        "frame_at_sec": data.get("at"),
        **result,
        "net_image_points": [[float(x), float(y)] for x, y in net_points],
        "court_size_ft": [20.0, 44.0],
        "net_y_ft": 22.0,
    }
    with open(os.path.join(job_dir, "calib.json"), "w") as f:
        json.dump(calib, f, indent=2)

    with _lock:
        _active_job["id"] = job_id
    threading.Thread(target=_run_job_thread, args=(job_id,), daemon=True).start()

    err_ft = result["per_point_error_ft"]
    worst = int(max(range(len(err_ft)), key=lambda k: err_ft[k]))
    return jsonify({"ok": True, "rmse_ft": result["reprojection_rmse_ft"],
                    "worst": POINTS[worst][0],
                    "redirect": url_for("status_page", job_id=job_id)})


def _run_job_thread(job_id):
    try:
        pipeline.run_job(os.path.join(JOBS_DIR, job_id))
    finally:
        with _lock:
            if _active_job["id"] == job_id:
                _active_job["id"] = None


@app.route("/job/<job_id>/status")
def status_page(job_id):
    _job_dir(job_id)
    return render_template("status.html", job_id=job_id)


@app.route("/job/<job_id>/status.json")
def status_json(job_id):
    job_dir = _job_dir(job_id)
    status = _read_status(job_dir)
    log_path = os.path.join(job_dir, "log.txt")
    tail = ""
    if os.path.exists(log_path):
        with open(log_path) as f:
            tail = "".join(f.readlines()[-80:])
    status["log_tail"] = tail
    return jsonify(status)


@app.route("/job/<job_id>")
def preview_page(job_id):
    job_dir = _job_dir(job_id)
    status = _read_status(job_dir)
    if not status.get("done") or status.get("stage") == "error":
        return redirect(url_for("status_page", job_id=job_id))
    return render_template("preview.html", job_id=job_id, stats=status.get("stats") or {})


def _reel_path(job_dir, which):
    status = _read_status(job_dir)
    return status.get("reel_ranked" if which == "ranked" else "reel_chronological")


@app.route("/job/<job_id>/video/<which>")
def serve_video(job_id, which):
    job_dir = _job_dir(job_id)
    path = _reel_path(job_dir, which)
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, conditional=True)


@app.route("/job/<job_id>/download/<which>")
def download_video(job_id, which):
    job_dir = _job_dir(job_id)
    path = _reel_path(job_dir, which)
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True)
