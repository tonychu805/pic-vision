import { useEffect, useState } from "react";
import { cleanIpcError } from "../lib/ipcError.js";
import { frameRateLevel, frameRateProblem, frameRateWarning } from "../../electron/cameras/frameRate.js";
import { cardVisuals, detailPanels } from "../lib/cameraView.js";
import { useI18n } from "../i18n.jsx";

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
  const { t } = useI18n();
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
          <span style={{ width: 8, height: 8, flex: "none", borderRadius: "50%", background: "var(--color-success)", animation: "blip 1.4s ease-in-out infinite" }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: "var(--fs-body)", fontWeight: 500 }}>{t("detail.recording", { elapsed: formatElapsed(status.startedAt) })}</div>
            <div style={{ fontSize: "var(--fs-fine)", fontFamily: "var(--font-mono)", color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {t("detail.savingTo", { dir: status.outDir })}
            </div>
          </div>
        </>
      ) : (
        <div className="text-3" style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-body)" }}>
          {t("detail.notRecording")}
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
  const { t } = useI18n();
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
      setError(t("detail.notLoaded"));
      setStarting(false);
      return;
    }
    try {
      const { url: liveUrl } = await window.liveViewAPI.start(camera.id);
      setUrl(liveUrl);
    } catch (err) {
      setError(cleanIpcError(err, t));
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
      <button className="btn btn-secondary" style={{ fontSize: "var(--fs-body)" }} onClick={openLiveView}>
        <i className="ph ph-play-circle" style={{ fontSize: 15 }} />{t("detail.liveView")}
      </button>
      {open && (
        <div className="dialog-backdrop" onClick={close}>
          <div className="dialog" style={{ width: "min(720px, 100%)" }} onClick={(e) => e.stopPropagation()}>
            <div className="dialog-title">{t("detail.liveTitle", { label: camera.label })}</div>
            <div className="dialog-body" style={{ padding: 0 }}>
              {error ? (
                <p style={{ padding: 16, fontSize: "var(--fs-body)", color: "var(--color-danger)" }}>{error}</p>
              ) : starting ? (
                <p style={{ padding: 16, fontSize: "var(--fs-body)", color: "var(--text-3)" }}>{t("common.connecting")}</p>
              ) : (
                <img
                  src={url}
                  alt={t("detail.liveAlt", { label: camera.label })}
                  style={{ display: "block", width: "100%", aspectRatio: "16/9", objectFit: "contain", background: "#000" }}
                  onError={() => setError(t("detail.liveLost"))}
                />
              )}
            </div>
            <div className="dialog-actions">
              <button className="btn btn-secondary" onClick={close}>{t("common.close")}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

const isSampleClip = (camera) => camera.connectionType === "sampleClip";

// Recording (ADR-080) and calibration (ADR-080/084) both moved to the
// cloud console, and this page had grown three separate "…from the cloud
// console" sentences saying so -- in the recording panel, in the
// calibration line, and implicitly wherever else a control used to be.
// Three dead ends telling you to go somewhere with no way to get there.
// One line, once, with a button that opens it.
function ConsolePointer() {
  const { t } = useI18n();
  const [url, setUrl] = useState(null);

  useEffect(() => {
    window.cloudAPI?.status?.().then((c) => setUrl(c?.consoleUrl ?? null)).catch(() => {});
  }, []);

  return (
    <div className="notice notice-quiet" style={{ marginTop: 14, alignItems: "center" }}>
      <i className="ph ph-cloud" style={{ fontSize: 15, flex: "none" }} />
      <span style={{ flex: 1, minWidth: 0 }}>
        {t("detail.consolePointer")}
      </span>
      {url && (
        <button
          className="btn btn-ghost"
          style={{ flex: "none", fontSize: "var(--fs-body)" }}
          onClick={() => window.systemAPI?.openExternal?.(url)}
        >
          {t("detail.openConsole")}<i className="ph ph-arrow-square-out" style={{ fontSize: 13 }} />
        </button>
      )}
    </div>
  );
}

// The one camera setting that stops everything working (ADR-087). Shown
// here rather than only in the collapsed "Streams" detail panel, because a
// camera below the floor is refused for both recording and calibration and
// the venue needs to know why without going looking.
//
// Reads electron/cameras/frameRate.js itself -- the actual gate -- rather
// than a copy of its thresholds (2026-09-29). The copy that lived here still
// blocked below 29 after ADR-131 lowered the floor to 25, so it told venues
// "recording and calibration are disabled" for cameras that were recording.
function FrameRateWarning({ camera }) {
  const { t } = useI18n();
  const level = frameRateLevel(camera);
  if (level === "ok") return null;
  if (level === "unknown") {
    return (
      <div className="notice notice-quiet" style={{ marginBottom: 10 }}>
        <i className="ph ph-question text-3" style={{ fontSize: 15, flex: "none", marginTop: 1 }} />
        <span>
          {t("detail.fps.unknown")}
        </span>
      </div>
    );
  }
  const blocked = level === "blocked";
  return (
    <div className={`notice ${blocked ? "notice-danger" : "notice-warning"}`} style={{ marginBottom: 10 }}>
      <i className="ph ph-warning" style={{ fontSize: 15, color: blocked ? "var(--color-danger)" : "var(--color-warning)", flex: "none", marginTop: 1 }} />
      <span>
        {blocked && <b>{t("detail.fps.blockedPrefix")}</b>}
        {blocked ? frameRateProblem(camera, t) : frameRateWarning(camera, t)}
      </span>
    </div>
  );
}

// Calibration is entirely the cloud console's now (ADR-080 moved the
// click-through UI there; ADR-084 moved the homography fit itself to the
// operator's job runner). This machine holds no calib.json at all -- the
// fitted calibration lives on the camera's console row, and cameras:list
// merges the state in from the last heartbeat response. So this is a
// read-only indicator: there is nothing here for the operator to set.
function CalibrationControl({ camera }) {
  const { t } = useI18n();
  const rmse = typeof camera.calibrationRmseFt === "number" ? camera.calibrationRmseFt : null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: "var(--fs-body)", flexWrap: "wrap" }}>
      <span className="text-3" style={{ flex: "none" }}>{t("detail.calibration")}</span>
      <span style={{ flex: 1, minWidth: 0 }}>
        {camera.isCalibrated
          ? (rmse !== null ? t("detail.calibratedRmse", { rmse: rmse.toFixed(2) }) : t("detail.calibrated"))
          : t("detail.notCalibrated")}
      </span>
    </div>
  );
}

// Coarse status only (2026-10-05) -- this used to be a hand-copied map of
// every cloud_pipeline/run_cloud_job.py stage name, and it had already
// drifted from what pod_driver.py (the code that actually runs today)
// emits: 'setup' and 'input_check' had no entry at all (shown as raw
// text), the real 'cut' stage had no entry either (its intended label
// sat under a 'reel' key nothing emits), and 'pod_create'/'pod_install'/
// 'pod_download' could never fire (pod_driver.py doesn't exist yet during
// that phase) -- three dead entries. Rather than fix the list, it's gone:
// whoever opens this screen is occasional and rarely the same person
// twice (operator, venue staff on a one-off task, a system integrator),
// so a fine-grained pipeline trace assumes a continuity of attention
// nobody in that position has, and nobody here can act on "pod_create"
// or "running TrackNet inference" regardless. That detail now belongs on
// the console (Cameras page badge + Reels page failed-job card, PIC-137
// follow-up), checked by whoever's actually tracking it, repeatedly, not
// read once off this one machine's screen.
function coarseStageLabel(stage, t) {
  if (stage === "upload") return t("detail.stage.upload");
  if (stage === "done") return t("detail.stage.done");
  if (stage === "cancelling") return t("detail.stage.cancelling");
  if (stage === "cancelled") return t("detail.stage.cancelled");
  if (stage === "error") return t("detail.stage.error");
  // Everything else -- queued, download, calibrate, drift_check, convert,
  // proxy, r2_upload, input_check, inference, cut, r2_download, and any
  // future pod_driver.py stage -- is "somewhere in the cloud pipeline,"
  // which is all a one-off viewer here could act on anyway.
  return t("detail.stage.processing");
}

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
  const { t } = useI18n();
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    const poll = () => window.pipelineAPI.statusForRecording(recording.dir).then(setStatus);
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, [recording.dir]);

  // Awaited, and the status re-read immediately. The old version fired
  // this and ignored both the promise and the result, so even once the
  // cancel worked nothing on screen changed until the next poll tick --
  // which, during an upload, is a row still counting segments upward.
  const cancel = async () => {
    setCancelling(true);
    setError("");
    try {
      const result = await window.pipelineAPI.cancel(recording.dir);
      if (result?.consoleError) setError(t("detail.cancelUnconfirmed"));
    } catch (err) {
      setError(cleanIpcError(err, t));
    }
    setStatus(await window.pipelineAPI.statusForRecording(recording.dir));
    setCancelling(false);
  };

  const start = async () => {
    setStarting(true);
    setError("");
    try {
      await window.pipelineAPI.run({ cameraId: camera.id, recordingDir: recording.dir });
      setStatus(await window.pipelineAPI.statusForRecording(recording.dir));
    } catch (err) {
      setError(cleanIpcError(err, t));
    }
    setStarting(false);
  };

  const hasRun = status?.stage != null;
  const running = hasRun && !TERMINAL_STAGES.has(status.stage);
  // A failed or cancelled attempt must not be the end of the road -- until
  // this fix, hasRun stayed true forever once anything had run once, and
  // the only button ever shown again was Cancel (which only renders while
  // running). A real venue recording hit this live, 2026-09-10: the pod
  // failed on a bad RunPod host and there was no way to try again short of
  // deleting local state by hand. runCloudJob() itself already tolerates a
  // second call once the first job reaches a terminal state (pollUntilDone
  // clears the `active` guard) -- this was purely a renderer-side gap.
  // Deliberately excludes "done": a successful job is not a failure, and a
  // live check against a real completed job (Court 3) caught an earlier
  // version of this line offering "Retry" on a job that had actually worked.
  const failed = status?.stage === "error" || status?.stage === "cancelled";
  const stageLabel = status?.stage ? coarseStageLabel(status.stage, t) : null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--hairline)", fontSize: "var(--fs-body)" }}>
      <span style={{ flex: 1, minWidth: 0, fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {t(recording.segments === 1 ? "detail.recordingLine.one" : "detail.recordingLine.many", { name: recording.name, n: recording.segments })}
      </span>
      {(!hasRun || failed) && (
        <button className="btn btn-ghost" style={{ fontSize: "var(--fs-fine)", flex: "none" }} disabled={starting || recording.recording || !camera.isCalibrated} onClick={start}>
          {starting ? t("detail.starting") : recording.recording ? t("detail.stillRecording") : !camera.isCalibrated ? t("detail.calibrateFirst") : failed ? t("detail.retry") : t("detail.sendToCloud")}
        </button>
      )}
      {error && <span style={{ flex: "none", color: "var(--color-danger)" }}>{error}</span>}
      {hasRun && (
        <>
          <span style={{ flex: "none", color: status.stage === "error" ? "var(--color-danger)" : "var(--text-2)" }}>
            {stageLabel}
            {/* Only during the real upload: current/total means something
                here (this machine's own segment count). A pod-side
                progress reading (e.g. inference frame counts) isn't
                meaningful to someone who can't act on it anyway, now that
                the stage itself collapses to "Processing in the cloud…". */}
            {status.stage === "upload" && status.progress ? ` (${status.progress.current}/${status.progress.total})` : ""}
          </span>
          {running && status.stage !== "cancelling" && (
            <button
              className="btn btn-ghost"
              style={{ fontSize: "var(--fs-fine)", flex: "none" }}
              disabled={cancelling}
              onClick={cancel}
            >
              {cancelling ? t("detail.stopping") : t("detail.cancel")}
            </button>
          )}
        </>
      )}
    </div>
  );
}

// A recording sent in parts (autoSplit.js), or one still recording: one
// status row per part already sent, instead of the whole recording's single
// Send button -- sending the whole recording as well would process every
// part twice. While recording, "Send what's recorded so far" sends every
// finished piece now, for when the session is about to end.
function PartedRecording({ camera, recording, onChanged }) {
  const { t } = useI18n();
  const [splitMinutes, setSplitMinutes] = useState(0);
  const [sending, setSending] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => { window.autoSplitAPI?.get().then((r) => setSplitMinutes(r.minutes)); }, []);

  const sendNow = async () => {
    setSending(true);
    setNote("");
    try {
      const { sent } = await window.autoSplitAPI.sendNow(camera.id);
      setNote(sent.length ? t("detail.sentList", { list: sent.join(", ") }) : t("detail.nothingToSend"));
      onChanged?.();
    } catch (err) {
      setNote(cleanIpcError(err, t));
    }
    setSending(false);
  };

  return (
    <div style={{ padding: "7px 0", borderBottom: "1px solid var(--hairline)", fontSize: "var(--fs-body)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ flex: 1, minWidth: 0, fontFamily: "var(--font-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {t(recording.segments === 1 ? "detail.recordingLine.one" : "detail.recordingLine.many", { name: recording.name, n: recording.segments })}
        </span>
        {recording.recording && (splitMinutes > 0 ? (
          <button className="btn btn-ghost" style={{ fontSize: "var(--fs-fine)", flex: "none" }} disabled={sending} onClick={sendNow}>
            {sending ? t("detail.sending") : t("detail.sendSoFar")}
          </button>
        ) : (
          <span className="text-4" style={{ flex: "none", fontSize: "var(--fs-fine)" }}>{t("detail.stillRecording")}</span>
        ))}
      </div>
      {recording.recording && splitMinutes > 0 && (
        <p className="text-4" style={{ fontSize: "var(--fs-fine)", margin: "4px 0 0" }}>
          {t("detail.sendingParts", { n: splitMinutes })}
        </p>
      )}
      {note && <p className="text-3" style={{ fontSize: "var(--fs-fine)", margin: "4px 0 0" }}>{note}</p>}
      <div style={{ paddingLeft: 16 }}>
        {(recording.parts ?? []).map((p) => <CloudJobRow key={p.dir} camera={camera} recording={p} />)}
      </div>
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
  const { t } = useI18n();
  const [recordings, setRecordings] = useState([]);
  const [retention, setRetention] = useState(null);

  // Calibration state isn't local: it arrives from the console on the
  // agent's heartbeat (cloud.js's calibrationByCameraId), and cameras:list
  // merges whatever has arrived so far. On a fresh launch the renderer reads
  // that list *before* the first heartbeat answers, so every camera looks
  // uncalibrated -- and a camera opened in that window showed "Not
  // calibrated" with the button below stuck on a disabled "Calibrate first",
  // for a camera the console had calibrated days earlier (UAT, 2026-09-18).
  // Only navigating back to the list fixed it, because that remounts and
  // re-reads. Re-read here instead, and lift the corrected record so the
  // button sees it too.
  const syncCalibration = async () => {
    const fresh = (await window.cameraAPI.list()).find((c) => c.id === camera.id);
    if (!fresh) return; // removed elsewhere -- onCameraRemoved handles that path
    if (fresh.isCalibrated !== camera.isCalibrated || fresh.calibrationRmseFt !== camera.calibrationRmseFt) {
      onCameraUpdated?.(fresh);
    }
  };

  const refresh = () => {
    // Refresh sits directly above the calibration line, so it has to mean
    // "re-read everything in this card", not just the recordings list.
    syncCalibration();
    return Promise.all([
      window.captureAPI.listRecordings(camera.id).then(setRecordings),
      window.captureAPI.retentionSummary(camera.id).then(setRetention),
    ]);
  };
  useEffect(() => { refresh(); }, [camera.id]);

  // While something is recording, parts appear on their own (autoSplit.js
  // sends one every N minutes), so the list re-reads itself instead of
  // waiting for a Refresh press.
  const anyRecording = recordings.some((r) => r.recording);
  useEffect(() => {
    if (!anyRecording) return undefined;
    const interval = setInterval(() => {
      window.captureAPI.listRecordings(camera.id).then(setRecordings);
      window.captureAPI.retentionSummary(camera.id).then(setRetention);
    }, 15000);
    return () => clearInterval(interval);
  }, [camera.id, anyRecording]);

  // One heartbeat is 30s, so a slower cadence than the 2s job poll is
  // enough; this only has to correct itself once, shortly after launch.
  useEffect(() => {
    const interval = setInterval(syncCalibration, 5000);
    return () => clearInterval(interval);
  }, [camera.id, camera.isCalibrated, camera.calibrationRmseFt]);

  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <span className="section-label" style={{ marginBottom: 0 }}>{t("detail.pipeline.title")}</span>
        <button className="btn btn-ghost" style={{ fontSize: "var(--fs-fine)" }} onClick={refresh}>
          <i className="ph ph-arrows-clockwise" style={{ fontSize: 13 }} />{t("detail.pipeline.refresh")}
        </button>
      </div>
      <FrameRateWarning camera={camera} />
      <CalibrationControl camera={camera} />
      {retention && (retention.waitingAfterEndOfDay || retention.waitingForReel || retention.deletesAt || retention.recording) && (
        <p className="text-3" style={{ fontSize: "var(--fs-fine)", margin: "10px 0 0" }}>
          {retention.waitingAfterEndOfDay
            ? t(retention.waitingAfterEndOfDay === 1 ? "detail.pipeline.keptUntilReel.one" : "detail.pipeline.keptUntilReel.many", { n: retention.waitingAfterEndOfDay })
            : retention.waitingForReel
              ? t(retention.waitingForReel === 1 ? "detail.pipeline.waitingForReel.one" : "detail.pipeline.waitingForReel.many", { n: retention.waitingForReel })
              : retention.deletesAt
                ? t("detail.pipeline.deletesAt")
                : t("detail.pipeline.inUse")}
        </p>
      )}
      <div style={{ marginTop: 10 }}>
        {recordings.length === 0 ? (
          <p style={{ fontSize: "var(--fs-body)", color: "var(--text-3)", margin: 0 }}>
            {t("detail.pipeline.none")}
          </p>
        ) : (
          recordings.map((r) => (r.parts?.length || r.recording
            ? <PartedRecording key={r.dir} camera={camera} recording={r} onChanged={refresh} />
            : <CloudJobRow key={r.dir} camera={camera} recording={r} />))
        )}
      </div>
    </div>
  );
}

// The displayed stream URI has its credentials starred out (PIC-97 --
// the RTSP-direct fallback embeds them, and they used to sit in the DOM
// on every render). Copy still yields a URI you can paste straight into
// VLC: it asks the main process for the real one at click time, so the
// credentials exist for the length of a clipboard write rather than for
// the length of the session.
function CopyStreamUri({ cameraId }) {
  const { t } = useI18n();
  const [state, setState] = useState("idle");

  const copy = async () => {
    try {
      const uri = await window.cameraAPI.revealStreamUri(cameraId);
      if (!uri) return setState("failed");
      await navigator.clipboard.writeText(uri);
      setState("copied");
      setTimeout(() => setState("idle"), 1800);
    } catch {
      setState("failed");
    }
  };

  return (
    <button className="btn btn-ghost" style={{ fontSize: "var(--fs-fine)" }} onClick={copy} title={t("detail.copy.title")}>
      <i className={`ph ${state === "copied" ? "ph-check" : "ph-copy"}`} style={{ fontSize: 14 }} />
      {state === "copied" ? t("detail.copy.copied") : state === "failed" ? t("detail.copy.failed") : t("detail.copy.copy")}
    </button>
  );
}

// Re-enter a camera's username and password.
//
// Shown only when the camera is actually refusing them (`auth`), because
// this is a repair tool, not a settings panel -- offering it on a working
// camera invites someone to break one. Before this existed a camera whose
// password had changed showed "Sign-in needed" with nothing to click, and
// the only fix was to delete and re-add it, losing its recording history
// and calibration.
//
// The credentials are verified against the real camera before anything is
// saved (electron/cameras/store.js's updateCameraCredentials), so a typo
// can't replace working credentials with broken ones.
function CameraSignIn({ camera, onUpdated }) {
  const { t, rich } = useI18n();
  const [username, setUsername] = useState(camera.username ?? "");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    let updated;
    try {
      updated = await window.cameraAPI.updateCredentials(camera.id, username, password);
    } catch {
      // Deliberately not err.message verbatim (PIC-93): the underlying
      // text is "RTSP/1.0 401 Unauthorized" or an ONVIF SOAP fault, which
      // tells a venue owner nothing. The one thing worth saying is which
      // of the two things to check.
      setError(t("detail.signin.failed"));
      setSaving(false);
      return;
    }
    // Outside the try, and deliberately. By this point the credentials
    // have been verified against the real camera and written to the store
    // -- the save has SUCCEEDED. Calling the parent's callback inside the
    // try meant anything it threw (or its simply not being passed, since
    // the prop is optional) surfaced as "that didn't work", inviting the
    // operator to retype credentials that were already saved, or to delete
    // and re-add the camera and lose its history.
    onUpdated?.(updated);
  };

  return (
    <form className="card" style={{ marginTop: 14 }} onSubmit={submit}>
      <div className="section-label">{t("detail.signin.title")}</div>
      <p className="text-3" style={{ fontSize: "var(--fs-body)", margin: "0 0 12px", lineHeight: 1.5 }}>
        {t("detail.signin.body", { label: camera.label })}
        {camera.manufacturer?.toLowerCase().includes("tp-link") || /tapo/i.test(camera.model ?? "") ? (
          <>{rich("detail.signin.tapo", { account: <b>{t("detail.signin.tapoAccount")}</b> })}</>
        ) : null}
      </p>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
        <div className="field" style={{ flex: 1 }}>
          <label>{t("detail.signin.username")}</label>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label>{t("detail.signin.password")}</label>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="off"
          />
        </div>
        <button className="btn btn-primary" style={{ marginBottom: 2 }} disabled={saving || !username || !password}>
          {saving ? t("detail.signin.checking") : t("detail.signin.submit")}
        </button>
      </div>
      {error && (
        <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-body)", margin: "10px 0 0" }}>{error}</p>
      )}
    </form>
  );
}

// The known refusals updateCameraAddress (electron/cameras/store.js) throws
// in plain words, worth showing as they are. Anything else is the camera
// not answering, reported in words that say what to check (PIC-93).
// Keyed by the main process's own (English) refusal text -- store.js's
// ADDRESS_ERRORS -- so recognising one doesn't depend on the display language;
// what the operator reads is the translation.
const ADDRESS_REFUSALS = [
  [/^A sample clip has no address/, "detail.addr.sampleClip"],
  [/^Stop this camera's recording/, "detail.addr.recording"],
  [/^Another camera, (.*), already uses that address/, "detail.addr.taken"],
  [/^That address answers as a different camera/, "detail.addr.otherCamera"],
];

function describeAddressRefusal(message, t) {
  for (const [pattern, key] of ADDRESS_REFUSALS) {
    const match = pattern.exec(message);
    if (match) return t(key, { label: match[1] });
  }
  return null;
}

// Point this camera at its new address.
//
// Shown only while the camera isn't answering -- a repair tool, like the
// sign-in form above, not a setting to fiddle with on a working camera.
// Before this, a camera whose address changed (usually a router restart
// handing out new IPs) could only be removed and added again, and a
// re-added camera loses its calibration: it happened at the PGC field test.
// It stays the same camera here, so nothing is lost -- provided it IS the
// same camera, in the same place, which the page says plainly because an
// RTSP camera can't be checked.
export function CameraAddress({ camera, onUpdated }) {
  const { t } = useI18n();
  const [hostname, setHostname] = useState(camera.hostname ?? "");
  const [port, setPort] = useState(String(camera.port ?? ""));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    let updated;
    try {
      updated = await window.cameraAPI.updateAddress(camera.id, hostname.trim(), Number(port) || undefined);
    } catch (err) {
      const message = cleanIpcError(err, t);
      setError(describeAddressRefusal(message, t) ?? t("detail.addr.nothing"));
      setSaving(false);
      return;
    }
    // Outside the try, for the reason CameraSignIn gives: the save has
    // already succeeded by here.
    onUpdated?.(updated);
  };

  return (
    <form className="card" style={{ marginTop: 14 }} onSubmit={submit}>
      <div className="section-label">{t("detail.addr.title")}</div>
      <p className="text-3" style={{ fontSize: "var(--fs-body)", margin: "0 0 12px", lineHeight: 1.5 }}>
        {t("detail.addr.body", { label: camera.label, host: camera.hostname })}
      </p>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
        <div className="field" style={{ flex: 2 }}>
          <label>{t("detail.addr.ip")}</label>
          <input className="input" value={hostname} onChange={(e) => setHostname(e.target.value)} autoComplete="off" spellCheck={false} />
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label>{t("detail.addr.port")}</label>
          <input className="input" value={port} onChange={(e) => setPort(e.target.value.replace(/[^0-9]/g, ""))} inputMode="numeric" autoComplete="off" />
        </div>
        <button
          className="btn btn-primary"
          style={{ marginBottom: 2 }}
          disabled={saving || !hostname.trim() || (hostname.trim() === camera.hostname && String(camera.port ?? "") === port)}
        >
          {saving ? t("detail.addr.checking") : t("detail.addr.use")}
        </button>
      </div>
      {error && <p style={{ color: "var(--color-danger)", fontSize: "var(--fs-body)", margin: "10px 0 0" }}>{error}</p>}
    </form>
  );
}

function InfoPanel({ title, rows }) {
  return (
    <div className="card">
      <div className="section-label">{title}</div>
      {rows.map((row) => (
        <div key={row.k} style={{ display: "flex", gap: 10, padding: "5px 0", fontSize: "var(--fs-body)", borderBottom: "1px solid var(--hairline)" }}>
          <span style={{ width: 96, flex: "none", color: "var(--text-3)" }}>{row.k}</span>
          <span style={{ minWidth: 0, fontFamily: "var(--font-mono)", fontSize: "var(--fs-body)" }}>{row.v}</span>
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
  const { t } = useI18n();
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
        style={{ fontSize: "var(--fs-title)", fontFamily: "var(--font-heading)", height: "auto", padding: "2px 8px", maxWidth: 320 }}
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
      style={{ padding: 0, fontFamily: "var(--font-heading)", fontSize: "var(--fs-title)", lineHeight: 1.2, color: "var(--color-text)", justifyContent: "flex-start", gap: 8 }}
      onClick={() => setEditing(true)}
      title={t("detail.rename")}
    >
      {camera.label}
      <i className="ph ph-pencil-simple" style={{ fontSize: 15, color: "var(--text-4)" }} />
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
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);

  const remove = async () => {
    setRemoving(true);
    await window.cameraAPI.remove(camera.id);
    onRemoved();
  };

  if (!confirming) {
    return (
      <button className="btn btn-ghost" style={{ fontSize: "var(--fs-body)", flex: "none" }} onClick={() => setConfirming(true)}>
        <i className="ph ph-trash" style={{ fontSize: 14 }} />{t("detail.remove")}
      </button>
    );
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
      <span style={{ fontSize: "var(--fs-fine)", color: "var(--text-3)" }}>{t("detail.removeConfirm")}</span>
      <button className="btn btn-secondary" style={{ fontSize: "var(--fs-fine)" }} disabled={removing} onClick={() => setConfirming(false)}>{t("common.cancel")}</button>
      <button className="btn btn-primary" style={{ fontSize: "var(--fs-fine)", color: "var(--color-danger)", borderColor: "var(--color-danger)" }} disabled={removing} onClick={remove}>
        {removing ? t("detail.removing") : t("detail.removeYes")}
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
export default function CameraDetailPage({ card, onBack, onCameraRemoved, onCameraRenamed, onCameraReconnected }) {
  const { t } = useI18n();
  const v = cardVisuals(card, t);
  const panels = detailPanels(card.camera, t);
  // Collapsed by default (2026-09-01, operator's call) -- Identity/
  // Network/Streams is real data but genuinely technical (raw stream
  // URLs, ONVIF paths, MAC/serial fields that are often just "Not
  // available"), not something a venue owner needs in front of them
  // every time they open a camera. Same disclosure pattern as
  // ManualAddDialog's "Advanced settings" elsewhere in this app, not a
  // new one.
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="page">
      <button className="btn btn-ghost" style={{ fontSize: "var(--fs-body)", marginBottom: 8 }} onClick={onBack}>
        <i className="ph ph-arrow-left" style={{ fontSize: 14 }} />{t("detail.back")}
      </button>

      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 14 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <EditableCameraName camera={card.camera} onRenamed={onCameraRenamed} />
            <span className={v.stateTagClass}>{v.stateLabel}</span>
          </div>
          <div style={{ fontSize: "var(--fs-body)", color: "var(--text-3)", marginTop: 2 }}>
            {v.subtitle}{v.ip ? ` · ${v.ip}` : ""}
          </div>
        </div>
        {!isSampleClip(card.camera) && <LiveViewButton camera={card.camera} />}
      </div>

      {/* onCameraReconnected, not onCameraRenamed: updateCredentials only
          returns after the camera has accepted them, so the state genuinely
          changed and the card must stop saying "Sign-in needed" -- otherwise
          this form stays on screen after a successful sign-in and looks
          broken. A rename, by contrast, deliberately preserves the old
          state. */}
      {card.state === "auth" && (
        <CameraSignIn camera={card.camera} onUpdated={onCameraReconnected} />
      )}
      {card.state === "offline" && !isSampleClip(card.camera) && (
        <CameraAddress camera={card.camera} onUpdated={onCameraReconnected} />
      )}

      {isSampleClip(card.camera) ? (
        // No live stream to start/stop -- the one "recording" is the file
        // it was added with (capture.js's listRecordings returns it as a
        // single synthetic entry for the Cloud pipeline panel below).
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14, padding: "12px 16px", borderRadius: "var(--radius-md)", background: "var(--color-surface)", fontSize: "var(--fs-body)", color: "var(--text-3)" }}>
          <i className="ph ph-file-video" style={{ fontSize: 16, flex: "none" }} />
          {t("detail.sampleNote")}
        </div>
      ) : (
        <RecordingControl camera={card.camera} />
      )}
      <ConsolePointer />
      <CloudPipelineControl camera={card.camera} onCameraUpdated={onCameraRenamed} />

      <button
        type="button"
        className="btn btn-ghost"
        style={{ marginTop: 14, fontSize: "var(--fs-body)" }}
        onClick={() => setShowDetails((v) => !v)}
      >
        <i className={`ph ${showDetails ? "ph-caret-up" : "ph-caret-down"}`} style={{ fontSize: 13 }} />
        {showDetails ? t("detail.hideDetails") : t("detail.showDetails")}
      </button>
      {showDetails && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 10 }}>
            <InfoPanel title={t("detail.identity")} rows={panels.identity} />
            <InfoPanel title={t("detail.network")} rows={panels.network} />
          </div>

          <div className="card" style={{ marginTop: 14 }}>
            <div className="section-label">{t("detail.streams")}</div>
            {panels.streams.length === 0 ? (
              <p style={{ fontSize: "var(--fs-body)", color: "var(--text-3)", margin: 0 }}>
                {t("detail.noStream")}
              </p>
            ) : (
              panels.streams.map((s) => (
                <div key={s.label} style={{ display: "flex", alignItems: "center", gap: 12, padding: "7px 0", borderBottom: "1px solid var(--hairline)" }}>
                  <span className="tag tag-outline">{s.label}</span>
                  <span style={{ flex: 1, minWidth: 0, fontFamily: "var(--font-mono)", fontSize: "var(--fs-fine)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.url}</span>
                  <span style={{ fontSize: "var(--fs-fine)", color: "var(--text-3)" }}>{s.spec}</span>
                  <CopyStreamUri cameraId={card.camera.id} />
                </div>
              ))
            )}
          </div>
        </>
      )}


      {/* Removing a camera is permanent (electron-store, no undo) and used
          to sit in the top-right corner in the same ghost styling as
          "Live view", one careless click from the page's most benign
          action. Down here it's still one click away, just not adjacent
          to something you press routinely. */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18, paddingTop: 12, borderTop: "1px solid var(--hairline)" }}>
        <RemoveCameraControl camera={card.camera} onRemoved={onCameraRemoved} />
      </div>
    </div>
  );
}
