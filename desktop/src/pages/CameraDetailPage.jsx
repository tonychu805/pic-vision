import { useEffect, useRef, useState } from "react";
import { cardVisuals, detailPanels } from "../lib/cameraView.js";

function formatElapsed(startedAt) {
  const secs = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// Manual start/stop recording (PIC-66, 2026-09-01) -- the first real
// piece of "pull a live stream," not just verify one exists. Polls
// captureAPI.status every 2s rather than trusting only its own start/
// stop calls, so it stays correct if a recording was started/stopped
// from elsewhere (there's only ever one electron/capture.js process
// tracking this, but the UI shouldn't assume it's the only thing that
// touched it).
function RecordingControl({ camera }) {
  const [status, setStatus] = useState({ recording: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [, forceTick] = useState(0); // re-render every 2s so the elapsed-time text keeps moving

  useEffect(() => {
    const refresh = () => window.captureAPI.status(camera.id).then(setStatus);
    refresh();
    const interval = setInterval(() => { refresh(); forceTick((n) => n + 1); }, 2000);
    return () => clearInterval(interval);
  }, [camera.id]);

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const s = await window.captureAPI.start(camera.id);
      setStatus({ recording: true, ...s });
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  const stop = async () => {
    setBusy(true);
    await window.captureAPI.stop(camera.id);
    setStatus({ recording: false });
    setBusy(false);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14, padding: "12px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
      {status.recording ? (
        <>
          <span style={{ width: 8, height: 8, flex: "none", borderRadius: "50%", background: "var(--color-accent-2-400)", animation: "blip 1.4s ease-in-out infinite" }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500 }}>Recording · {formatElapsed(status.startedAt)}</div>
            <div style={{ fontSize: 11.5, fontFamily: "ui-monospace, Menlo, monospace", color: "color-mix(in srgb, var(--color-text) 50%, transparent)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              Saving to {status.outDir}
            </div>
          </div>
          <button className="btn btn-primary" style={{ fontSize: 12.5, flex: "none", color: "var(--color-accent-2-400)", borderColor: "var(--color-accent-2-400)" }} disabled={busy} onClick={stop}>
            {busy ? "Stopping…" : "Stop recording"}
          </button>
        </>
      ) : (
        <>
          <div style={{ flex: 1, minWidth: 0, fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>
            {error || `Recordings save to ~/pic-vision-recordings/${camera.label}/`}
          </div>
          <button className="btn btn-primary" style={{ fontSize: 12.5, flex: "none" }} disabled={busy} onClick={start}>
            <i className="ph ph-record" style={{ fontSize: 14 }} />{busy ? "Starting…" : "Start recording"}
          </button>
        </>
      )}
    </div>
  );
}

// Literal copy of calibrate.py's POINTS names (order matters -- this is
// the click order cloud_pipeline/save_calibration.py expects on stdin)
// plus its NET_PROMPTS, same "kept in sync by hand" convention as
// CLOUD_STAGE_LABELS below.
const CALIBRATION_LABELS = [
  "near-left corner (baseline x left sideline)",
  "near-right corner",
  "far-left corner",
  "far-right corner",
  "near NVZ line x left sideline",
  "near NVZ line x right sideline",
  "far NVZ line x left sideline",
  "far NVZ line x right sideline",
  "near centerline x baseline",
  "far centerline x baseline",
  "near centerline x NVZ line",
  "far centerline x NVZ line",
  "net tape - LEFT end (top of net)",
  "net tape - RIGHT end (top of net)",
];
const N_COURT_POINTS = 12;

// Takes a live snapshot from the camera and collects the 14 clicks in the
// browser-like flow webapp/app.py's calibrate_page/calibrate_save routes
// already use (calibrate.html's click-collection JS, ported to React) --
// replaces the earlier "pass an existing calib.json path in" scope (a bare
// file picker) PIC-68 shipped with. The actual homography fit stays in
// Python (calibration.js spawns cloud_pipeline/save_calibration.py), not
// reimplemented here.
const isSampleClip = (camera) => camera.connectionType === "sampleClip";

function CalibrationModal({ camera, onClose, onSaved }) {
  const [snapshot, setSnapshot] = useState(null); // { path, base64, atSec? }
  const [loadingSnapshot, setLoadingSnapshot] = useState(true);
  const [snapshotError, setSnapshotError] = useState("");
  const [points, setPoints] = useState([]);
  const [natural, setNatural] = useState({ w: 0, h: 0 });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [result, setResult] = useState(null);
  // Only meaningful for a sample-clip camera (a live camera has no
  // "seconds into the file" to seek) -- string, not number, so the input
  // can hold an in-progress edit like "12." without fighting the user.
  const [seekInput, setSeekInput] = useState("");

  const takeSnapshot = async (atSec) => {
    setLoadingSnapshot(true);
    setSnapshotError("");
    setPoints([]);
    setNatural({ w: 0, h: 0 });
    const stale = snapshot;
    setSnapshot(null);
    if (stale) window.calibrationAPI.discardSnapshot(stale.path);
    try {
      const s = await window.calibrationAPI.snapshot(camera.id, atSec);
      setSnapshot(s);
      if (s.atSec != null) setSeekInput(String(s.atSec));
    } catch (err) {
      setSnapshotError(err.message);
    }
    setLoadingSnapshot(false);
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { takeSnapshot(); }, []);

  // Real gap found 2026-09-03: navigating away (or the app quitting) while
  // this modal is open left its snapshot undiscarded in /tmp -- normally
  // disposable temp-file clutter, but a live camera's snapshot can be a
  // real, private frame, not something to leave lying around waiting for
  // the OS to eventually clean /tmp. A ref (not `snapshot` itself) so the
  // cleanup always sees the latest value without re-registering on every
  // snapshot change. discardSnapshot is a no-op if the file's already gone
  // (a completed Save or an explicit Cancel already removed it), so this
  // is safe to always attempt on unmount.
  const snapshotRef = useRef(null);
  snapshotRef.current = snapshot;
  useEffect(() => () => {
    if (snapshotRef.current) window.calibrationAPI.discardSnapshot(snapshotRef.current.path);
  }, []);

  const handleImgClick = (e) => {
    if (points.length >= CALIBRATION_LABELS.length) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const scale = natural.w / rect.width;
    setPoints((p) => [...p, [(e.clientX - rect.left) * scale, (e.clientY - rect.top) * scale]]);
  };

  const save = async () => {
    setSaving(true);
    setSaveError("");
    try {
      const r = await window.calibrationAPI.save(camera.id, snapshot.path, points);
      setResult(r);
      onSaved(r.camera);
    } catch (err) {
      setSaveError(err.message);
    }
    setSaving(false);
  };

  const cancel = () => {
    if (snapshot) window.calibrationAPI.discardSnapshot(snapshot.path);
    onClose();
  };

  const total = CALIBRATION_LABELS.length;
  const done = points.length === total;

  return (
    <div className="dialog-backdrop">
      <div className="dialog" style={{ width: "min(940px, 96vw)" }}>
        <div className="dialog-title">Calibrate {camera.label}</div>
        {result ? (
          <>
            <div className="dialog-body">
              Saved -- reprojection error <b>{result.rmseFt.toFixed(3)} ft</b>
              {result.rmseFt > 0.5
                ? ` (worse than 0.5 ft; worst point was "${result.worst}" -- consider recalibrating)`
                : " (looks good)"}.
            </div>
            <div className="dialog-actions">
              <button className="btn btn-primary" onClick={onClose}>Done</button>
            </div>
          </>
        ) : loadingSnapshot ? (
          <div className="dialog-body">Taking a snapshot from the camera…</div>
        ) : snapshotError ? (
          <>
            <div className="dialog-body" style={{ color: "var(--color-accent-2-400)" }}>{snapshotError}</div>
            <div className="dialog-actions">
              <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" onClick={takeSnapshot}>Retry</button>
            </div>
          </>
        ) : (
          <>
            <div className="dialog-body">
              Click: <b>{done ? "all 14 placed -- ready to save" : CALIBRATION_LABELS[points.length]}</b>
              <span style={{ marginLeft: 10, opacity: 0.7 }}>{points.length} / {total} placed</span>
            </div>
            {isSampleClip(camera) && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
                <span style={{ color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Frame at</span>
                <input
                  className="input"
                  type="number"
                  min="0"
                  step="1"
                  value={seekInput}
                  onChange={(e) => setSeekInput(e.target.value)}
                  style={{ width: 80 }}
                />
                <span style={{ color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>seconds</span>
                <button type="button" className="btn btn-ghost" onClick={() => takeSnapshot(Number(seekInput) || 0)}>
                  Reload frame
                </button>
              </div>
            )}
            <div style={{ position: "relative", display: "inline-block", maxHeight: "60vh", overflow: "auto", background: "#000", borderRadius: "var(--radius-md)" }}>
              <img
                src={`data:image/png;base64,${snapshot.base64}`}
                onLoad={(e) => setNatural({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
                onClick={handleImgClick}
                style={{ display: "block", maxWidth: "100%", cursor: done ? "default" : "crosshair" }}
                draggable={false}
              />
              {natural.w > 0 && (
                <svg
                  viewBox={`0 0 ${natural.w} ${natural.h}`}
                  style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
                >
                  {points.map(([x, y], i) => {
                    const net = i >= N_COURT_POINTS;
                    return (
                      <g key={i}>
                        <circle cx={x} cy={y} r={6} fill={net ? "#f33" : "#0f0"} />
                        <text x={x + 9} y={y - 9} fill="#ff0" fontSize={14} fontWeight="bold">
                          {net ? `N${i - N_COURT_POINTS + 1}` : String(i + 1)}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
            </div>
            {saveError && <p style={{ color: "var(--color-accent-2-400)", fontSize: 13, margin: 0 }}>{saveError}</p>}
            <div className="dialog-actions" style={{ justifyContent: "space-between" }}>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" className="btn btn-ghost" disabled={points.length === 0} onClick={() => setPoints((p) => p.slice(0, -1))}>Undo</button>
                <button type="button" className="btn btn-ghost" disabled={points.length === 0} onClick={() => setPoints([])}>Reset</button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => takeSnapshot(isSampleClip(camera) ? Number(seekInput) || 0 : undefined)}
                >
                  Retake snapshot
                </button>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" className="btn btn-secondary" onClick={cancel}>Cancel</button>
                <button type="button" className="btn btn-primary" disabled={!done || saving} onClick={save}>
                  {saving ? "Saving…" : "Save calibration"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// The file picker (system.js's pickCalibFile) stays available as a
// secondary "Import a file instead" option -- a calibration produced
// elsewhere (e.g. cloud_pipeline/setup_venue_calibration.py, or another
// camera's already-clicked calib.json for a venue that reuses a mount)
// shouldn't force re-clicking 14 points against this camera's own stream.
function CalibrationControl({ camera, onUpdated }) {
  const [open, setOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");

  // Same silent-failure class found in ManualAddDialog's "Choose file…"
  // button (2026-09-03): with no try/catch, a main-process change that
  // hadn't taken effect yet (a full app restart is needed, not just
  // Vite's renderer hot-reload) made window.systemAPI.pickCalibFile
  // undefined -- the click would otherwise fail invisibly instead of
  // saying so.
  const importFile = async () => {
    setImporting(true);
    setImportError("");
    if (typeof window.systemAPI?.pickCalibFile !== "function") {
      setImportError("This feature isn't loaded yet -- fully quit and restart the app (not just reload the window).");
      setImporting(false);
      return;
    }
    try {
      const picked = await window.systemAPI.pickCalibFile();
      if (picked) onUpdated(await window.cameraAPI.setCalibPath(camera.id, picked));
    } catch (err) {
      setImportError(err.message);
    }
    setImporting(false);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, flexWrap: "wrap" }}>
      <span style={{ flex: "none", color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Calibration:</span>
      <span style={{ flex: 1, minWidth: 0, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {camera.calibPath || "not set"}
      </span>
      <button className="btn btn-ghost" style={{ fontSize: 12, flex: "none" }} disabled={importing} onClick={importFile}>
        Import file…
      </button>
      <button className="btn btn-ghost" style={{ fontSize: 12, flex: "none" }} onClick={() => setOpen(true)}>
        {camera.calibPath ? "Recalibrate" : "Calibrate"}
      </button>
      {importError && (
        <p style={{ flex: "1 0 100%", margin: 0, fontSize: 12, color: "var(--color-accent-2-400)" }}>{importError}</p>
      )}
      {open && <CalibrationModal camera={camera} onClose={() => setOpen(false)} onSaved={onUpdated} />}
    </div>
  );
}

// STAGES from cloud_pipeline/run_cloud_job.py -- kept as a literal copy
// here the same way webapp/pipeline.py falls back to one when it can't
// import cloud_pipeline (a JS renderer never can); update by hand if that
// list changes.
const CLOUD_STAGE_LABELS = {
  drift_check: "Checking camera drift",
  convert: "Converting to 30fps CFR",
  proxy: "Creating 720p upload proxy",
  r2_upload: "Uploading to cloud storage",
  pod_create: "Creating RunPod GPU pod",
  pod_install: "Installing dependencies on pod",
  pod_download: "Downloading video onto pod",
  inference: "Running TrackNet inference",
  r2_download: "Downloading results",
  reel: "Detecting rallies, cutting reel",
  done: "Done",
  error: "Failed",
  cancelled: "Cancelled",
};

// A job's terminal stages -- everything else in CLOUD_STAGE_LABELS is
// still in progress. status.json has no separate "done" boolean; `stage`
// itself is the only signal.
const TERMINAL_STAGES = new Set(["done", "error", "cancelled"]);

// One row per recording under this camera -- PIC-68's "send to cloud"
// trigger. Polls pipeline:statusForRecording every 2s unconditionally
// (not only after this component instance's own start() call) so an
// already-running job's progress survives navigating away from the camera
// detail page and back -- real gap found 2026-09-03: the old version kept
// jobDir in local `job` state alone, which reset to null on remount and
// made a job that was still running server-side look like it had vanished.
// Same 2s interval RecordingControl already uses for capture:status, not a
// different cadence invented for this.
function CloudJobRow({ camera, recording }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    const poll = () => window.pipelineAPI.statusForRecording(recording.dir).then(setStatus);
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [recording.dir]);

  const start = async () => {
    setStarting(true);
    setError("");
    try {
      await window.pipelineAPI.run({ cameraId: camera.id, recordingDir: recording.dir });
      setStatus(await window.pipelineAPI.statusForRecording(recording.dir));
    } catch (err) {
      setError(err.message);
    }
    setStarting(false);
  };

  const hasRun = status?.stage != null;
  const running = hasRun && !TERMINAL_STAGES.has(status.stage);
  const stageLabel = status?.stage ? (CLOUD_STAGE_LABELS[status.stage] || status.stage) : null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)", fontSize: 12.5 }}>
      <span style={{ flex: 1, minWidth: 0, fontFamily: "ui-monospace, Menlo, monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {recording.name} ({recording.segments} segment{recording.segments === 1 ? "" : "s"})
      </span>
      {!hasRun && (
        <button className="btn btn-ghost" style={{ fontSize: 12, flex: "none" }} disabled={starting || recording.recording || !camera.calibPath} onClick={start}>
          {starting ? "Starting…" : recording.recording ? "Still recording" : "Send to cloud"}
        </button>
      )}
      {error && <span style={{ flex: "none", color: "var(--color-accent-2-400)" }}>{error}</span>}
      {hasRun && (
        <>
          <span style={{ flex: "none", color: status.stage === "error" ? "var(--color-accent-2-400)" : "color-mix(in srgb, var(--color-text) 60%, transparent)" }}>
            {stageLabel}{status.progress ? ` (${status.progress.current}/${status.progress.total})` : ""}
          </span>
          {running && (
            <button className="btn btn-ghost" style={{ fontSize: 12, flex: "none" }} onClick={() => window.pipelineAPI.cancel(recording.dir)}>
              Cancel
            </button>
          )}
        </>
      )}
    </div>
  );
}

// Hands finished recordings to cloud_pipeline/run_desktop_job.py as a
// subprocess (PIC-68) -- the local agent doesn't reimplement R2 upload/
// RunPod dispatch/reel-cutting in JS, per ADR-071's "reuse the existing
// Python" directive. No auto-refresh of the recordings list beyond
// mount -- a manual "Refresh" avoids surprising a job row mid-poll if a
// new recording starts while this page is open.
function CloudPipelineControl({ camera, onCameraUpdated }) {
  const [recordings, setRecordings] = useState([]);

  const refresh = () => window.captureAPI.listRecordings(camera.id).then(setRecordings);
  useEffect(() => { refresh(); }, [camera.id]);

  return (
    <div style={{ marginTop: 14, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)" }}>Cloud pipeline</span>
        <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={refresh}>
          <i className="ph ph-arrows-clockwise" style={{ fontSize: 13 }} />Refresh
        </button>
      </div>
      <CalibrationControl camera={camera} onUpdated={onCameraUpdated} />
      <div style={{ marginTop: 10 }}>
        {recordings.length === 0 ? (
          <p style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", margin: 0 }}>
            No recordings yet.
          </p>
        ) : (
          recordings.map((r) => <CloudJobRow key={r.dir} camera={camera} recording={r} />)
        )}
      </div>
    </div>
  );
}

function InfoPanel({ title, rows }) {
  return (
    <div style={{ padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
      <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>{title}</div>
      {rows.map((row) => (
        <div key={row.k} style={{ display: "flex", gap: 10, padding: "5px 0", fontSize: 13, borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
          <span style={{ width: 96, flex: "none", color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>{row.k}</span>
          <span style={{ minWidth: 0, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12.5 }}>{row.v}</span>
        </div>
      ))}
    </div>
  );
}

// Click the name to rename it in place -- name only, not connection
// details (hostname/port/path/credentials aren't editable yet, that
// would need the same re-verification addCamera/addCameraViaRtsp do
// before saving, which renameCamera doesn't attempt).
function EditableCameraName({ camera, onRenamed }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(camera.label);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const label = value.trim();
    if (!label || label === camera.label) {
      setEditing(false);
      setValue(camera.label);
      return;
    }
    setSaving(true);
    const updated = await window.cameraAPI.rename(camera.id, label);
    setSaving(false);
    setEditing(false);
    onRenamed(updated);
  };

  if (editing) {
    return (
      <input
        className="input"
        autoFocus
        style={{ fontSize: 20, fontFamily: "var(--font-heading)", height: "auto", padding: "2px 8px", maxWidth: 320 }}
        value={value}
        disabled={saving}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") { setValue(camera.label); setEditing(false); }
        }}
      />
    );
  }

  return (
    <button
      className="btn btn-ghost"
      style={{ padding: 0, fontFamily: "var(--font-heading)", fontSize: 24, lineHeight: 1.2, color: "var(--color-text)", justifyContent: "flex-start", gap: 8 }}
      onClick={() => setEditing(true)}
      title="Rename this camera"
    >
      {camera.label}
      <i className="ph ph-pencil-simple" style={{ fontSize: 15, color: "color-mix(in srgb, var(--color-text) 40%, transparent)" }} />
    </button>
  );
}

// Two-step: "Remove camera" first shows an inline confirm rather than
// removing on the first click (a real camera + its schedule are both
// gone for good -- electron-store, no undo) or using window.confirm's
// native OS dialog, which would look inconsistent against this app's own
// custom-drawn chrome.
function RemoveCameraControl({ camera, onRemoved }) {
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);

  const remove = async () => {
    setRemoving(true);
    await window.cameraAPI.remove(camera.id);
    onRemoved();
  };

  if (!confirming) {
    return (
      <button className="btn btn-ghost" style={{ fontSize: 12.5, flex: "none" }} onClick={() => setConfirming(true)}>
        <i className="ph ph-trash" style={{ fontSize: 14 }} />Remove camera
      </button>
    );
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
      <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Remove this camera and its schedule?</span>
      <button className="btn btn-secondary" style={{ fontSize: 12 }} disabled={removing} onClick={() => setConfirming(false)}>Cancel</button>
      <button className="btn btn-primary" style={{ fontSize: 12, color: "var(--color-accent-2-400)", borderColor: "var(--color-accent-2-400)" }} disabled={removing} onClick={remove}>
        {removing ? "Removing…" : "Remove"}
      </button>
    </div>
  );
}

// A configured camera's detail page only, now -- an unconfigured card
// (found via WS-Discovery or the RTSP sweep, `kind !== "configured"`)
// goes straight to ManualAddDialog from the grid instead (CamerasPage.jsx,
// 2026-09-01: one workflow to connect a camera regardless of how it was
// found, replacing this page's own separate, weaker inline sign-in form
// -- ONVIF-only, no RTSP fallback if it failed).
export default function CameraDetailPage({ card, onBack, onCameraRemoved, onCameraRenamed }) {
  const v = cardVisuals(card);
  const panels = detailPanels(card.camera);
  // Collapsed by default (2026-09-01, operator's call) -- Identity/
  // Network/Streams is real data but genuinely technical (raw stream
  // URLs, ONVIF paths, MAC/serial fields that are often just "Not
  // available"), not something a venue owner needs in front of them
  // every time they open a camera. Same disclosure pattern as
  // ManualAddDialog's "Advanced settings" elsewhere in this app, not a
  // new one.
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "18px 22px 26px" }}>
      <button className="btn btn-ghost" style={{ fontSize: 12.5, marginBottom: 8 }} onClick={onBack}>
        <i className="ph ph-arrow-left" style={{ fontSize: 14 }} />All cameras
      </button>

      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <EditableCameraName camera={card.camera} onRenamed={onCameraRenamed} />
            <span className={v.stateTagClass}>{v.stateLabel}</span>
          </div>
          <div style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", marginTop: 2 }}>
            {v.subtitle}{v.ip ? ` · ${v.ip}` : ""}
          </div>
        </div>
        <RemoveCameraControl camera={card.camera} onRemoved={onCameraRemoved} />
      </div>

      {isSampleClip(card.camera) ? (
        // No live stream to start/stop -- the one "recording" is the file
        // it was added with (capture.js's listRecordings returns it as a
        // single synthetic entry for the Cloud pipeline panel below).
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14, padding: "12px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>
          <i className="ph ph-file-video" style={{ fontSize: 16, flex: "none" }} />
          Sample clip -- no live stream to record. Its one "recording" is the uploaded file itself, below.
        </div>
      ) : (
        <RecordingControl camera={card.camera} />
      )}
      <CloudPipelineControl camera={card.camera} onCameraUpdated={onCameraRenamed} />

      <button
        type="button"
        className="btn btn-ghost"
        style={{ marginTop: 14, fontSize: 12.5 }}
        onClick={() => setShowDetails((v) => !v)}
      >
        <i className={`ph ${showDetails ? "ph-caret-up" : "ph-caret-down"}`} style={{ fontSize: 13 }} />
        {showDetails ? "Hide camera details" : "Show camera details"}
      </button>

      {showDetails && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 10 }}>
            <InfoPanel title="Identity" rows={panels.identity} />
            <InfoPanel title="Network" rows={panels.network} />
          </div>

          <div style={{ marginTop: 14, padding: "14px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)" }}>
            <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 10 }}>Streams</div>
            {panels.streams.length === 0 ? (
              <p style={{ fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 50%, transparent)", margin: 0 }}>
                No stream URI on record for this camera.
              </p>
            ) : (
              panels.streams.map((s) => (
                <div key={s.label} style={{ display: "flex", alignItems: "center", gap: 12, padding: "7px 0", borderBottom: "1px solid color-mix(in srgb, var(--color-text) 6%, transparent)" }}>
                  <span className="tag tag-outline">{s.label}</span>
                  <span style={{ flex: 1, minWidth: 0, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.url}</span>
                  <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 50%, transparent)" }}>{s.spec}</span>
                  <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => navigator.clipboard.writeText(s.url)}>
                    <i className="ph ph-copy" style={{ fontSize: 14 }} />Copy
                  </button>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
