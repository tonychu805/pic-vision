import { useEffect, useState } from "react";
import { cardVisuals, detailPanels } from "../lib/cameraView.js";

function formatElapsed(startedAt) {
  const secs = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// Read-only recording status (2026-09-05, ADR-080) -- Start/Stop moved to
// the cloud console entirely (ADR-077 built the console-side control,
// verified against a real camera earlier the same day; this is the
// flagged follow-up: "the desktop app's own recording button should come
// out of desktop/... not kept in both places"). Still polls
// captureAPI.status every 2s, since an operator standing at this machine
// should still be able to see it's working -- just nothing here can
// start or stop it anymore.
function RecordingControl({ camera }) {
  const [status, setStatus] = useState({ recording: false });
  const [, forceTick] = useState(0); // re-render every 2s so the elapsed-time text keeps moving

  useEffect(() => {
    const refresh = () => window.captureAPI.status(camera.id).then(setStatus);
    refresh();
    const interval = setInterval(() => { refresh(); forceTick((n) => n + 1); }, 2000);
    return () => clearInterval(interval);
  }, [camera.id]);

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
        </>
      ) : (
        <div style={{ flex: 1, minWidth: 0, fontSize: 12.5, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>
          Not recording — start it from the cloud console
        </div>
      )}
    </div>
  );
}

// On-demand live view (operator's proposal, 2026-09-05): a popup showing
// the real RTSP stream, started only while this modal is open and
// stopped the moment it closes -- deliberately not an always-on preview,
// to keep the bandwidth/CPU cost occasional rather than continuous. The
// <img> tag itself is what actually renders the MJPEG-over-HTTP stream
// (see electron/liveview.js); this component just owns start/stop and
// the connecting/error states around it.
function LiveViewButton({ camera }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const openLiveView = async () => {
    setOpen(true);
    setStarting(true);
    setError("");
    // A main-process/preload change (like liveViewAPI itself) only takes
    // effect after a full quit-and-relaunch, not a renderer reload/hot-
    // reload -- same gap CloudPage.jsx's CLOUD_API_MISSING already had to
    // learn from once. Checked here, not just left to throw, so a stale
    // build says so instead of a bare "cannot read properties of
    // undefined".
    if (typeof window.liveViewAPI?.start !== "function") {
      setError("This feature isn't loaded yet -- fully quit and restart the app (not just reload the window).");
      setStarting(false);
      return;
    }
    try {
      const { url: liveUrl } = await window.liveViewAPI.start(camera.id);
      setUrl(liveUrl);
    } catch (err) {
      setError(err.message);
    }
    setStarting(false);
  };

  const close = () => {
    setOpen(false);
    setUrl(null);
    window.liveViewAPI?.stop();
  };

  return (
    <>
      <button className="btn btn-secondary" style={{ fontSize: 12.5 }} onClick={openLiveView}>
        <i className="ph ph-play-circle" style={{ fontSize: 15 }} />Live view
      </button>
      {open && (
        <div className="dialog-backdrop" onClick={close}>
          <div className="dialog" style={{ width: "min(720px, 100%)" }} onClick={(e) => e.stopPropagation()}>
            <div className="dialog-title">{camera.label} -- live</div>
            <div className="dialog-body" style={{ padding: 0 }}>
              {error ? (
                <p style={{ padding: 16, fontSize: 13, color: "var(--color-accent-2-400)" }}>{error}</p>
              ) : starting ? (
                <p style={{ padding: 16, fontSize: 13, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Connecting…</p>
              ) : (
                <img
                  src={url}
                  alt={`${camera.label} live view`}
                  style={{ display: "block", width: "100%", aspectRatio: "16/9", objectFit: "contain", background: "#000" }}
                  onError={() => setError("Lost connection to the camera's stream.")}
                />
              )}
            </div>
            <div className="dialog-actions">
              <button className="btn btn-secondary" onClick={close}>Close</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

const isSampleClip = (camera) => camera.connectionType === "sampleClip";

// The 14-point click-through calibration flow moved to the cloud console
// entirely (2026-09-05, ADR-080, superseding ADR-077's "scoped out, not
// just deferred" call on this) -- desktop keeps only the file-picker
// fallback (system.js's pickCalibFile), since that's a local-filesystem
// recovery path, not "performing calibration" the interactive way: a
// calibration produced elsewhere (cloud_pipeline/setup_venue_calibration.py,
// or another camera's already-clicked calib.json for a venue that reuses
// a mount) shouldn't need the console's UI at all, and nothing about it
// needs LAN/camera access, so there's no reason to route it through a
// command round-trip either.
function CalibrationControl({ camera, onUpdated }) {
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
        {camera.calibPath || "not set — calibrate from the cloud console"}
      </span>
      <button className="btn btn-ghost" style={{ fontSize: 12, flex: "none" }} disabled={importing} onClick={importFile}>
        Import file…
      </button>
      {importError && (
        <p style={{ flex: "1 0 100%", margin: 0, fontSize: 12, color: "var(--color-accent-2-400)" }}>{importError}</p>
      )}
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
// removing on the first click (a real camera is gone for good --
// electron-store, no undo) or using window.confirm's native OS dialog,
// which would look inconsistent against this app's own custom-drawn
// chrome. Doesn't touch that camera's cloud schedule (ADR-071/PIC-73,
// 2026-09-04) -- Schedule lives entirely in the cloud console now, not
// something this local removal can or should reach into.
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
      <span style={{ fontSize: 12, color: "color-mix(in srgb, var(--color-text) 55%, transparent)" }}>Remove this camera?</span>
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
        {!isSampleClip(card.camera) && <LiveViewButton camera={card.camera} />}
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
