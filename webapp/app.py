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
from werkzeug.utils import secure_filename

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from calibrate import POINTS, NET_PROMPTS, compute_calibration, solve_assignment
from webapp import pipeline

JOBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

# Per-venue calibrations for the cloud route (cloud_pipeline/venues/<name>/
# calib.json) -- one-time per venue, unlike the local route's fresh
# per-job calibration. See cloud_pipeline/run_cloud_job.py's own comment
# on why those two cadences can't be conflated.
VENUES_DIR = os.path.join(REPO_ROOT, "cloud_pipeline", "venues")

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


def _venue_dir(name, must_exist=False):
    """Resolves a venue name to cloud_pipeline/venues/<name>, rejecting
    anything secure_filename() would alter (spaces, slashes, ..) rather than
    silently sanitizing to a different name -- this path gets used to build
    real filesystem paths from user input, so a mismatch here should be a
    400, not a silent traversal risk."""
    safe = secure_filename(name or "")
    if not safe or safe != name:
        abort(400, "invalid venue name -- use only letters, numbers, dashes, underscores")
    path = os.path.join(VENUES_DIR, safe)
    if must_exist and not os.path.isdir(path):
        abort(404)
    return path


def _list_venues():
    if not os.path.isdir(VENUES_DIR):
        return []
    return sorted(
        entry for entry in os.listdir(VENUES_DIR)
        if os.path.exists(os.path.join(VENUES_DIR, entry, "calib.json"))
    )


def _find_staging_video(venue_dir):
    for entry in os.listdir(venue_dir):
        if entry.startswith("_calib_source"):
            return os.path.join(venue_dir, entry)
    return None


@app.route("/")
def home():
    return render_template("home.html", busy=_job_busy())


@app.route("/local")
def local_index():
    return render_template("upload.html", busy=_job_busy(),
                           default_target_sec=int(DEFAULT_TARGET_SEC))


@app.route("/local/upload", methods=["POST"])
def upload():
    if _job_busy():
        return "a job is already running -- wait for it to finish first", 409
    f = request.files.get("video")
    if not f or not f.filename:
        return redirect(url_for("local_index"))
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
                   "session_id": job_id, "backend": "local"}, jf, indent=2)

    return redirect(url_for("calibrate_page", job_id=job_id))


@app.route("/cloud")
def cloud_index():
    return render_template("cloud_upload.html", busy=_job_busy(),
                           default_target_sec=int(DEFAULT_TARGET_SEC),
                           venues=_list_venues())


@app.route("/cloud/upload", methods=["POST"])
def cloud_upload():
    if _job_busy():
        return "a job is already running -- wait for it to finish first", 409
    venue = request.form.get("venue") or ""
    venue_dir = _venue_dir(venue, must_exist=True)
    calib_path = os.path.join(venue_dir, "calib.json")
    if not os.path.exists(calib_path):
        return f"venue '{venue}' has no calib.json -- set it up first", 400

    f = request.files.get("video")
    if not f or not f.filename:
        return redirect(url_for("cloud_index"))
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
                   "session_id": job_id, "backend": "cloud",
                   "venue": venue, "calib_path": calib_path}, jf, indent=2)

    # Unlike the local route, no calibration step -- the venue's calib.json
    # already exists, so the job can start running immediately.
    with _lock:
        _active_job["id"] = job_id
    threading.Thread(target=_run_cloud_job_thread, args=(job_id,), daemon=True).start()

    return redirect(url_for("status_page", job_id=job_id))


def _run_cloud_job_thread(job_id):
    try:
        pipeline.run_cloud_job(os.path.join(JOBS_DIR, job_id))
    finally:
        with _lock:
            if _active_job["id"] == job_id:
                _active_job["id"] = None


@app.route("/cloud/new-venue")
def new_venue_form():
    return render_template("new_venue.html")


@app.route("/cloud/new-venue", methods=["POST"])
def new_venue_upload():
    venue = request.form.get("venue") or ""
    venue_dir = _venue_dir(venue)
    calib_path = os.path.join(venue_dir, "calib.json")
    if os.path.exists(calib_path):
        return (f"venue '{venue}' is already calibrated -- this is a one-time "
                f"setup step, not something to redo per session. Delete "
                f"{calib_path} first if the camera actually moved.", 400)

    f = request.files.get("video")
    if not f or not f.filename:
        return redirect(url_for("new_venue_form"))
    ext = os.path.splitext(f.filename)[1]
    if ext not in ALLOWED_EXT:
        return f"unsupported file type {ext}", 400

    os.makedirs(venue_dir, exist_ok=True)
    f.save(os.path.join(venue_dir, "_calib_source" + ext))

    return redirect(url_for("venue_calibrate_page", name=venue))


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
    return render_template("calibrate.html", frame_b64=frame_b64,
                           w=w, h=h, labels=json.dumps(labels), n_court=len(POINTS),
                           at=at, duration_int=int(round(duration)),
                           save_url=url_for("calibrate_save", job_id=job_id),
                           reload_url=url_for("calibrate_page", job_id=job_id))


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

    video_path = os.path.join(job_dir, job["video_file"])
    cap = cv2.VideoCapture(video_path)
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    calib = {
        "video": job["video_file"],
        "frame_at_sec": data.get("at"),
        **result,
        "net_image_points": [[float(x), float(y)] for x, y in net_points],
        "court_size_ft": [20.0, 44.0],
        "net_y_ft": 22.0,
        # See calibrate.py's identical field for why this is needed.
        "calibration_resolution": [frame_w, frame_h],
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


@app.route("/cloud/new-venue/<name>/calibrate")
def venue_calibrate_page(name):
    venue_dir = _venue_dir(name, must_exist=True)
    staging_video = _find_staging_video(venue_dir)
    if not staging_video:
        return "no uploaded video for this venue setup -- start over", 400

    _, probe_duration = _grab_frame(staging_video, 0.0)
    default_at = round(probe_duration * 0.10, 1) if probe_duration else 10.0
    at = float(request.args.get("at", default_at))

    frame_b64, duration = _grab_frame(staging_video, at)
    if frame_b64 is None:
        return f"could not read a frame at {at}s (video is {duration:.0f}s long)", 400

    cap = cv2.VideoCapture(staging_video)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    labels = [pname for pname, _ in POINTS] + list(NET_PROMPTS)
    return render_template("calibrate.html", frame_b64=frame_b64,
                           w=w, h=h, labels=json.dumps(labels), n_court=len(POINTS),
                           at=at, duration_int=int(round(duration)),
                           save_url=url_for("venue_calibrate_save", name=name),
                           reload_url=url_for("venue_calibrate_page", name=name))


@app.route("/cloud/new-venue/<name>/calibrate/save", methods=["POST"])
def venue_calibrate_save(name):
    venue_dir = _venue_dir(name, must_exist=True)
    calib_path = os.path.join(venue_dir, "calib.json")
    if os.path.exists(calib_path):
        return jsonify({"error": "this venue is already calibrated"}), 409

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

    staging_video = _find_staging_video(venue_dir)
    if not staging_video:
        # venue_calibrate_page() (the GET route) already requires this file
        # to exist before it'll render anything to click on, so reaching
        # here without one means it was removed mid-flow -- fail loudly
        # rather than write a calib.json with a broken/missing
        # calibration_resolution that a later cloud job would silently
        # trust.
        return jsonify({"error": "staging video is gone -- start over"}), 400
    cap = cv2.VideoCapture(staging_video)
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    calib = {
        "video": name,
        "frame_at_sec": data.get("at"),
        **result,
        "net_image_points": [[float(x), float(y)] for x, y in net_points],
        "court_size_ft": [20.0, 44.0],
        "net_y_ft": 22.0,
        # See calibrate.py's identical field for why this is needed.
        "calibration_resolution": [frame_w, frame_h],
    }
    with open(calib_path, "w") as f:
        json.dump(calib, f, indent=2)

    # The staging video was only needed to grab a calibration frame -- not
    # kept afterward, matching this project's convention of never committing
    # or retaining raw video (regenerable, and here not even needed again).
    if staging_video:
        os.remove(staging_video)

    err_ft = result["per_point_error_ft"]
    worst = int(max(range(len(err_ft)), key=lambda k: err_ft[k]))
    return jsonify({"ok": True, "rmse_ft": result["reprojection_rmse_ft"],
                    "worst": POINTS[worst][0],
                    "redirect": url_for("cloud_index")})


def _run_job_thread(job_id):
    try:
        pipeline.run_job(os.path.join(JOBS_DIR, job_id))
    finally:
        with _lock:
            if _active_job["id"] == job_id:
                _active_job["id"] = None


@app.route("/job/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    job_dir = _job_dir(job_id)
    # Clear the busy lock immediately, regardless of how long the
    # background thread takes to actually notice and unwind (it may be
    # blocked inside a subprocess/ssh call) -- the operator's actual ask was
    # "let me restart", not "wait for the old thread to fully exit first".
    # pipeline.cancel_job() stops the real resource (local process or
    # RunPod pod) synchronously before this returns, so nothing keeps
    # running -- or billing -- unattended.
    with _lock:
        if _active_job["id"] == job_id:
            _active_job["id"] = None
    pipeline.cancel_job(job_dir)
    return jsonify({"ok": True})


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


def _reel_presigned_url(job_dir, which):
    # A cloud job's reel lives only in R2 since ADR-074 (cut on the pod,
    # never downloaded locally) -- status.json carries a bucket/key pair
    # instead of a local path for that case. A local job's reel keeps using
    # the plain local-file route above; this is checked first only because
    # a cloud job's status has no reel_ranked path at all.
    #
    # Cloud jobs only ever have a ranked key (2026-09-04: pod_cut.py stopped
    # cutting a chronological version at all) -- which="chronological" on a
    # cloud job falls through to `key = None` below and this function
    # returns None, same as a local job's reel not existing yet; the caller
    # already 404s on that, nothing cloud-specific needed here.
    status = _read_status(job_dir)
    bucket = status.get("reel_bucket")
    key = status.get("reel_ranked_key") if which == "ranked" else None
    if not bucket or not key:
        return None
    from cloud_pipeline import r2_storage
    return r2_storage.generate_presigned_url(bucket, key)


@app.route("/job/<job_id>/video/<which>")
def serve_video(job_id, which):
    job_dir = _job_dir(job_id)
    url = _reel_presigned_url(job_dir, which)
    if url:
        return redirect(url)
    path = _reel_path(job_dir, which)
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, conditional=True)


@app.route("/job/<job_id>/download/<which>")
def download_video(job_id, which):
    job_dir = _job_dir(job_id)
    url = _reel_presigned_url(job_dir, which)
    if url:
        return redirect(url)
    path = _reel_path(job_dir, which)
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True)
