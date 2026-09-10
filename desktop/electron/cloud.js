// First real outbound connectivity from the local agent to the cloud
// console (ADR-071's "polls or a lightweight persistent connection for
// commands/status, never an inbound port"). Pairing + a heartbeat that
// also reports the real camera list (2026-09-03). Reel reporting (ADR-074,
// 2026-09-04) happens on the console side now (ADR-084) once the job
// runner reports a finished job, not from this machine. Schedule migrated to
// the cloud console entirely the same day (ADR-071/PIC-73) -- no local
// schedule.js left to report on. Same electron-store-per-concern
// convention as cameras/store.js.
import { randomUUID } from "node:crypto";
import { hostname } from "node:os";
import Store from "electron-store";
import { listCameras, testConnection, setCameraProfile } from "./cameras/store.js";
import { classifyProbeError, describeProbeState } from "./cameras/probeResult.js";
import { isRecording, listRecordings, startRecording, stopRecording, measureStreamFps, measureStreamProfile, authenticatedStreamUri } from "./capture.js";
import { grabAndUploadSnapshot } from "./calibration.js";
import { basename } from "node:path";
import { runCloudJob } from "./pipeline.js";
import { logEvent } from "./activityLog.js";
import { encryptField, decryptField } from "./secureField.js";

// configFileMode 0600: owner-only, and set here rather than chmod-ed
// afterwards -- see activityLog.js for why that distinction matters.
const store = new Store({ name: "cloud", configFileMode: 0o600 });

// Defaults to the real production console -- same pattern as auth.js's
// SUPABASE_URL/SUPABASE_ANON_KEY, overridable via env var for local dev
// against `pnpm dev`'s localhost:3000, never the other way around.
//
// Found 2026-09-05 while QCing the Disconnect feature: this used to
// default to localhost:3000, which only ever worked by accident because
// every call site that mattered already had a real stored consoleUrl to
// reuse. registerDevice() (auth.js) does not -- it's the one path that
// falls all the way back to this default, and it's exactly what the
// "Connect to the cloud console" retry button and the auto-register-at-
// launch check both call. Neither had ever been exercised against a
// live, already-signed-in device without a working connection until
// this session's revoke testing hit it for the first time -- surfaced
// as a generic "TypeError: fetch failed" (a real connection refusal to
// a port nothing was listening on), not an HTTP error, so it looked
// environmental at first rather than a wrong URL.
const DEFAULT_CONSOLE_URL = process.env.PIC_VISION_CLOUD_URL || "https://console.picvisionai.com";

const HEARTBEAT_INTERVAL_MS = 30_000;

let heartbeatTimer = null;

// Registration is started automatically after sign-in and, if that first
// attempt has not completed when the Cloud console page opens, an operator
// can also click its retry button.  Those are intentionally two ways to
// recover from an offline console, but they must share the *same* request:
// two simultaneous register calls can both observe no agent row and race to
// insert the same stable device_id.  The database correctly rejects the
// second insert as a duplicate.  Keep the promise (rather than only a
// boolean) so every caller receives the successful connection or the same
// actionable failure.
let registrationInFlight = null;

// Transition-tracking for the activity log -- both start "assumed fine"
// (undefined for a camera means "no prior reading yet," true for the
// heartbeat means "just connected/registered") so the very first
// heartbeat tick after a launch or a fresh registration doesn't log a
// spurious "recovered" the moment it succeeds; only an actual change from
// a previously-known state logs anything.
const lastCameraStatus = new Map(); // cameraId -> "online" | "offline"
let lastHeartbeatOk = true;

// Calibration state as last reported by the console (ADR-084 -- the
// console owns it now, there's no local calib.json anymore). Refreshed on
// every heartbeat response; read by main.js's cameras:list so the UI can
// show it and gate "send to cloud" on it. Empty until the first heartbeat
// lands, which reads as "not calibrated yet" -- correct for an unpaired
// or freshly-launched agent.
const calibrationByCameraId = new Map(); // cameraId -> { isCalibrated, calibrationRmseFt, calibratedAt }

// Re-measuring what a camera is actually sending. Deliberately not
// once-per-run: an operator who changes a camera's frame rate in its own
// web page gets no signal from us otherwise, which is exactly what
// happened -- the setting changed and both the app and the console kept
// showing the old number indefinitely.
//
// Three triggers, cheapest first:
//   - never measured, or missing fields this camera type can supply
//   - the ONVIF-reported (configured) rate changed since we last measured,
//     which IS the "someone changed the setting" signal
//   - the measurement has simply gone stale
//
// Skipped while a camera is recording: the probe opens a second RTSP
// session and some cameras allow only one. A finished recording is
// re-measured on stop anyway (runCommand), which is better evidence.
const MEASURE_TTL_MS = 10 * 60 * 1000;

// Only to stop two probes racing for the same camera -- never to stop a
// repeat, which was the original bug.
const measuringNow = new Set();

function needsMeasuring(camera) {
  const p = camera.profile ?? {};
  if (p.measuredFps == null) return true;
  if (camera.connectionType !== "onvif"
      && (p.codec == null || p.width == null || p.height == null || p.bitrateKbps == null)) return true;
  // A changed configured rate means the camera was reconfigured, so the
  // stored measurement describes the old setting and must not outlive it.
  // This matters because effectiveFps() prefers the measured value: a
  // stale one would override the fresh configured one indefinitely.
  if (p.measuredAtFps != null && p.fps != null && p.measuredAtFps !== p.fps) return true;
  if (!p.measuredAt) return true;
  return Date.now() - new Date(p.measuredAt).getTime() > MEASURE_TTL_MS;
}

async function refreshMeasuredProfile(camera) {
  if (measuringNow.has(camera.id) || isRecording(camera.id)) return;
  if (!needsMeasuring(camera)) return;

  // A sample clip is a local file (milliseconds); a live camera means
  // holding its stream open for a few seconds. Both land in the same
  // field, so one path covers all three connection types.
  const source = camera.connectionType === "sampleClip"
    ? camera.sampleClipPath
    : camera.streamUri && authenticatedStreamUri(camera);
  if (!source) return;

  measuringNow.add(camera.id);
  try {
    const measured = await measureStreamProfile(source);
    if (!measured) return;
    const { fps, ...rest } = measured;
    // An ONVIF camera already reported codec/resolution/bitrate, and those
    // describe what it's configured to send; only its rate is topped up.
    // Everything else has no other source, so take the lot.
    const extra = camera.connectionType === "onvif" ? {} : rest;
    setCameraProfile(camera.id, {
      ...(camera.profile ?? {}), ...extra,
      measuredFps: fps,
      measuredAt: new Date().toISOString(),
      // What the camera said it was set to when this was measured, so a
      // later change to that setting invalidates it.
      measuredAtFps: camera.profile?.fps ?? null,
    });
  } finally {
    measuringNow.delete(camera.id);
  }
}

export function getCalibrationState(cameraId) {
  return calibrationByCameraId.get(cameraId) ?? { isCalibrated: false, calibrationRmseFt: null, calibratedAt: null };
}

export function getCloudConnection() {
  const connection = store.get("connection", null);
  if (!connection) return connection;
  return { ...connection, apiToken: decryptField(connection.apiToken) };
}

// Encrypts apiToken before it touches disk -- this is the long-lived
// credential a revoked device can never get back (see the revoke API
// route on the console), so the same class of secret as a camera
// password or a Supabase session token. A decryption failure (vault
// cleared, moved machines) just resolves as a null apiToken above,
// which fails the same normal way a genuinely revoked token already
// does -- a real 401 on the next heartbeat, logged and recoverable via
// the existing "Connect to the cloud console" retry.
function saveConnection(connection) {
  store.set("connection", { ...connection, apiToken: encryptField(connection.apiToken) });
}

// A stable identity for this machine, independent of connection state --
// generated once and kept even across disconnectCloud() (unlike
// "connection", which is cleared there). Without this, every
// re-registration (including a retried/failed attempt against the wrong
// URL) minted a brand-new `agents` row server-side with no way to
// recognize "this is the same desktop as before" -- duplicate agents
// *and* duplicate cameras, since camera-heartbeat sync just re-inserts
// under whatever agent_id the current token maps to. The register
// endpoint uses this to reclaim the existing row for this device instead.
export function getOrCreateDeviceId() {
  let id = store.get("deviceId");
  if (!id) {
    id = randomUUID();
    store.set("deviceId", id);
  }
  return id;
}

// Operator-editable label for this machine on the console's "Connected
// agents" table (Overview page) -- every agent row otherwise shows the
// same DB default ("Desktop agent"), useless once a brand has more than
// one. Defaults to the machine's hostname so it's not blank before the
// operator ever visits the Cloud console page. Synced on every heartbeat
// rather than only at registration time, so a rename takes effect within
// one interval without needing to re-register.
export function getAgentName() {
  return store.get("agentName", hostname());
}

export function setAgentName(name) {
  const trimmed = String(name ?? "").trim();
  if (!trimmed) return getAgentName();
  store.set("agentName", trimmed);
  sendHeartbeat(); // push the rename immediately rather than waiting for the next interval
  return trimmed;
}

// Registers this machine as its own agent row, using the signed-in
// operator's own Supabase session instead of a manually-typed pairing
// code (DECISIONS.md ADR-079, superseding ADR-078's "keep both" -- since
// one account owns exactly one brand, signing in already identifies which
// brand this device belongs to, so there's nothing left for a code to
// prove). Called automatically right after a successful sign-in
// (auth.js's `registerDevice`), not something the operator triggers by
// hand. `accessToken` is the caller's problem to keep valid -- this
// function doesn't refresh it, same as it never touched the pairing code
// it replaced.
//
// The returned long-lived API token is OS-vault-encrypted at rest the
// same way camera passwords are (secureField.js, PIC-79) -- see
// saveConnection above.
export function registerAgent(accessToken, userId, consoleUrl = DEFAULT_CONSOLE_URL) {
  if (registrationInFlight) return registrationInFlight;

  registrationInFlight = registerAgentOnce(accessToken, userId, consoleUrl)
    .finally(() => { registrationInFlight = null; });
  return registrationInFlight;
}

async function registerAgentOnce(accessToken, userId, consoleUrl) {
  const res = await fetch(`${consoleUrl}/api/agents/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ deviceId: getOrCreateDeviceId(), agentName: getAgentName() }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `device registration failed (HTTP ${res.status})`);

  store.delete("disconnectedByUser"); // a deliberate reconnection
  const connection = {
    consoleUrl,
    agentId: body.agentId,
    apiToken: body.apiToken,
    brandName: body.brandName,
    // Which account this device is registered AS. Without it, signing out
    // and signing in as a different account left the old account's agent
    // id, token and brand in place -- the app said "Connected as <the
    // other brand>" and, worse, kept heartbeating and would have filed
    // every camera and reel under it (2026-09-09, ADR-094).
    userId,
    connectedAt: new Date().toISOString(),
  };
  saveConnection(connection);
  lastHeartbeatOk = true; // fresh connection -- don't let a stale prior failure log a false "reconnected" on the first tick
  logEvent("cloud_connected", `Connected to the cloud console (${body.brandName})`);
  startHeartbeatLoop();
  return connection;
}

/**
 * Stamps the signed-in account onto a connection that predates `userId`
 * (any build before 2026-09-09), without re-registering.
 *
 * Used only when the stored brand still matches the signed-in account's
 * brand -- i.e. nothing actually changed hands, the record was just
 * missing a field. A genuine mismatch is never resolved silently; it
 * asks (ADR-094).
 */
export function adoptConnection(userId) {
  const connection = getCloudConnection();
  if (!connection) return null;
  const adopted = { ...connection, userId };
  saveConnection(adopted);
  return adopted;
}

export function disconnectCloud() {
  stopHeartbeatLoop();
  store.delete("connection");
  // Remembered, because the app re-registers a signed-in device that has
  // no connection every time it launches (that retry exists for a first
  // registration that failed). Without this flag, Disconnect undid itself
  // on the next launch and the button was quietly lying. Cleared by any
  // deliberate reconnection: signing in again, or the Connect button.
  store.set("disconnectedByUser", true);
}

/** Did someone press Disconnect, rather than never having connected? */
export function wasDisconnectedByUser() {
  return store.get("disconnectedByUser", false) === true;
}

// startRecording's outDir name is new Date().toISOString() with ':' and
// '.' replaced by '-' (capture.js, filesystem-safe). Reversing that back
// into a real ISO timestamp for the cloud side rather than re-deriving
// "when did this session start" a second way -- the directory name
// already is that answer.
function parseRecordingStartedAt(name) {
  const m = name?.match(/^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z$/);
  return m ? `${m[1]}T${m[2]}:${m[3]}:${m[4]}.${m[5]}Z` : null;
}

// Live-checks every configured camera the same way CamerasPage.jsx's own
// "checking" -> testConnection -> ok/offline flow already does (no new
// health-check logic invented) -- but from the main process, on the
// heartbeat's own schedule, so status is fresh even with no renderer
// window open. Only non-sensitive identity/state fields are reported --
// hostname/port/username/password/streamUri never leave this machine,
// per ADR-071's "camera-facing data stays local" (a stream URI can embed
// credentials for an RTSP camera, so it's excluded same as the rest).
// calibPath/sampleClipPath are local filesystem paths (can embed the
// OS username), so only a derived boolean/count crosses -- never the
// path itself.
async function cameraStatuses() {
  const cameras = listCameras();
  const results = await Promise.allSettled(cameras.map((c) => testConnection(c)));
  return cameras.map((c, i) => {
    const recordings = listRecordings(c);
    const status = results[i].status === "fulfilled" ? "online" : "offline";
    // The connection check above already asked the camera what it's
    // streaming; keep it rather than discard it. Backfills cameras added
    // before this existed, and picks up a setting changed on the camera's
    // own web page without anyone re-adding it here.
    const profile = results[i].status === "fulfilled" ? results[i].value?.profile ?? null : null;
    if (profile) setCameraProfile(c.id, profile);
    // Fire-and-forget: the result lands in the store for the next tick
    // rather than holding this heartbeat open for it.
    if (results[i].status === "fulfilled") {
      refreshMeasuredProfile(c).catch((err) => console.error(`[cloud] fps check failed for ${c.label}: ${err.message}`));
    }
    const previous = lastCameraStatus.get(c.id);
    if (previous && previous !== status) {
      if (status === "online") {
        logEvent("camera_online", `${c.label} came back online`);
      } else {
        // Say WHY, and carry the raw message as the detail line. Without
        // this the log said "went offline" for a camera that had answered
        // "401 Unauthorized", and the actual reason existed nowhere at all
        // -- which is what made the 2026-09-07 report undiagnosable from
        // inside the app. The badge stays two words; this is where the
        // detail lives (Log tab rows expand).
        const { state, detail } = classifyProbeError(results[i].reason, c.connectionType);
        logEvent("camera_offline", describeProbeState(state, c.label), detail);
      }
    }
    lastCameraStatus.set(c.id, status);
    return {
      cameraId: c.id,
      label: c.label,
      connectionType: c.connectionType,
      manufacturer: c.manufacturer ?? null,
      model: c.model ?? null,
      status,
      firmwareVersion: c.firmwareVersion ?? null,
      serialNumber: c.serialNumber ?? null,
      addedAt: c.addedAt ?? null,
      isRecording: isRecording(c.id),
      // What this camera is actually sending, so the console can see which
      // venues stream H.265 or run below 30fps -- both change how well
      // detection works, and neither was visible anywhere before.
      codec: profile?.codec ?? c.profile?.codec ?? null,
      streamWidth: profile?.width ?? c.profile?.width ?? null,
      streamHeight: profile?.height ?? c.profile?.height ?? null,
      streamFps: profile?.fps ?? c.profile?.fps ?? null,
      // What actually arrives, which is what detection quality depends on.
      // Reported alongside the configured rate rather than instead of it:
      // the console needs both to tell "set wrong" from "network dropping
      // frames", which need opposite advice (ADR-087).
      streamMeasuredFps: c.profile?.measuredFps ?? null,
      streamBitrateKbps: profile?.bitrateKbps ?? c.profile?.bitrateKbps ?? null,
      recordingCount: recordings.length,
      lastRecordingAt: parseRecordingStartedAt(recordings[0]?.name),
    };
  });
}

async function sendHeartbeat() {
  const connection = getCloudConnection();
  if (!connection) return;

  const cameras = await cameraStatuses();
  try {
    const res = await fetch(`${connection.consoleUrl}/api/agents/heartbeat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${connection.apiToken}` },
      body: JSON.stringify({ cameraCount: cameras.length, cameras, agentName: getAgentName() }),
    });
    if (!res.ok) {
      // A rejected token (e.g. the agent row was deleted server-side)
      // isn't retried forever -- surfaces in status() instead of
      // silently hammering an endpoint that will never accept it again.
      console.error(`[cloud] heartbeat rejected: HTTP ${res.status}`);
      if (lastHeartbeatOk) logEvent("cloud_disconnected", "Lost connection to the cloud console", `HTTP ${res.status}`);
      lastHeartbeatOk = false;
      return;
    }
    if (!lastHeartbeatOk) logEvent("cloud_connected", "Reconnected to the cloud console");
    lastHeartbeatOk = true;
    // Keeps a Settings-page rename on the console reaching this already-
    // paired agent within one heartbeat cycle, instead of only ever
    // reflecting whatever the brand was named at pairing time.
    const body = await res.json().catch(() => ({}));
    if (typeof body.brandName === "string" && body.brandName !== connection.brandName) {
      saveConnection({ ...connection, brandName: body.brandName });
    }
    if (Array.isArray(body.cameras)) {
      calibrationByCameraId.clear();
      for (const c of body.cameras) {
        calibrationByCameraId.set(c.cameraId, {
          isCalibrated: Boolean(c.isCalibrated),
          calibrationRmseFt: c.calibrationRmseFt ?? null,
          calibratedAt: c.calibratedAt ?? null,
        });
      }
    }
  } catch (err) {
    // Console unreachable (offline venue, DNS hiccup, console down) --
    // logged, not thrown; the loop just tries again next interval rather
    // than crashing the agent over a transient network blip.
    console.error(`[cloud] heartbeat failed: ${err.message}`);
    if (lastHeartbeatOk) logEvent("cloud_disconnected", "Lost connection to the cloud console", err.message);
    lastHeartbeatOk = false;
  }
}

// The cloud->agent command channel (ADR-071/ADR-073's long-flagged missing
// piece, first built as ADR-077 for start/stop recording, extended by
// ADR-080 for calibration): the console creates a row in `agent_commands`
// (POST /api/commands) and this picks it up here, on the *same* heartbeat
// cadence -- no separate timer, no persistent connection, consistent with
// ADR-071's "polling is fine, none of this is latency-sensitive like live
// video" call. Recording/calibration both still have to run wherever the
// camera actually is, so this just calls the exact same capture.js/
// calibration.js functions desktop's own local controls used to call --
// only the trigger moved, not the action.
async function fetchPendingCommands(connection) {
  try {
    const res = await fetch(`${connection.consoleUrl}/api/agents/commands`, {
      headers: { Authorization: `Bearer ${connection.apiToken}` },
    });
    if (!res.ok) return [];
    const body = await res.json().catch(() => ({}));
    return Array.isArray(body.commands) ? body.commands : [];
  } catch (err) {
    console.error(`[cloud] fetching commands failed: ${err.message}`);
    return [];
  }
}

async function completeCommand(connection, commandId, status, result) {
  try {
    await fetch(`${connection.consoleUrl}/api/agents/commands/${commandId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${connection.apiToken}` },
      body: JSON.stringify({ status, result: result ?? null }),
    });
  } catch (err) {
    console.error(`[cloud] reporting command result failed: ${err.message}`);
  }
}

async function runCommand(command) {
  const camera = listCameras().find((c) => c.id === command.camera_id);
  if (!camera) throw new Error("camera not found");

  // The sample-clip guard only makes sense for recording -- a sample clip
  // has no live stream to capture, but it can absolutely be calibrated
  // (takeCalibrationSnapshot already seeks into the uploaded file for
  // exactly this case), so this can't be a blanket check above the
  // dispatch the way it used to be when recording was the only command.
  if (command.type === "start_recording" || command.type === "stop_recording") {
    if (camera.connectionType === "sampleClip") {
      throw new Error("sample-clip cameras have no live stream to record");
    }
  }

  if (command.type === "start_recording") return await startRecording(camera);
  if (command.type === "stop_recording") {
    const result = await stopRecording(camera.id);
    // Re-measure from what was actually captured. Free (a local file), more
    // truthful than probing the live stream, and the only thing that would
    // ever notice someone changing the camera's frame rate after it was
    // added -- an RTSP camera has no ONVIF profile the heartbeat could
    // refresh instead.
    if (result.measureFrom) {
      measureStreamFps(result.measureFrom)
        .then((fps) => { if (fps != null) setCameraProfile(camera.id, { ...(camera.profile ?? {}), measuredFps: fps }); })
        .catch((err) => console.error(`[cloud] post-recording fps check failed: ${err.message}`));
    }
    // A booked session has to produce a reel without anyone touching
    // anything -- that is the entire point of booking it. Stopping the
    // recording used to be where the scheduler's involvement ended, so a
    // scheduled session recorded to disk and sat there until someone
    // clicked "Send to cloud" by hand.
    //
    // Only for scheduled stops: `schedule_booking_id` is set by the
    // dispatcher (see the console's dispatch_due_schedule_bookings). A stop
    // the operator triggered themselves keeps its manual send, since
    // silently spending GPU money on a recording someone stopped by hand
    // isn't obviously wanted.
    if (result.stopped && result.outDir && command.params?.schedule_booking_id) {
      sendRecordingToCloud(camera, result.outDir);
    }
    return result;
  }
  // Console-driven calibration (ADR-080) -- see calibration.js's header
  // for why this replaced ADR-077's "scoped out" call on moving it here.
  if (command.type === "grab_calibration_snapshot") return await grabAndUploadSnapshot(camera);
  // apply_calibration is no longer an agent command (ADR-084): the fit
  // needs OpenCV, so it runs on the operator's job runner instead and the
  // console turns those clicks into a `jobs` row, not a command for us.
  //
  // send_to_cloud (PIC-136 follow-up, 2026-09-10): deliberately sample-clip
  // only. A live camera has a *history* of past recordings and no console
  // button could say which one it means without the bigger footage-upload-
  // order redesign PIC-136 punted on; a sample-clip camera has exactly one
  // recording (its own file -- see listRecordings' sampleClip branch), so
  // there's no ambiguity and nothing new to build: this just calls the same
  // sendRecordingToCloud() a scheduled booking's auto-send already uses.
  if (command.type === "send_to_cloud") {
    if (camera.connectionType !== "sampleClip") {
      throw new Error("send_to_cloud is only supported for sample-clip cameras");
    }
    const [recording] = listRecordings(camera);
    if (!recording) throw new Error("no sample clip file found for this camera");
    sendRecordingToCloud(camera, recording.dir);
    return { queued: true };
  }
  throw new Error(`unknown command type: ${command.type}`);
}

// Fire-and-forget: runCloudJob uploads in the background and tracks its own
// state in the recording's cloud_job/status.json, exactly as it does for a
// manual send, so nothing here needs to wait for it. Failures are logged to
// the activity log by runCloudJob itself.
function sendRecordingToCloud(camera, recordingDir) {
  const sessionId = `${camera.label}-${basename(recordingDir)}`.replace(/[^a-zA-Z0-9._-]+/g, "_");
  runCloudJob({
    recordingDir,
    videoPath: camera.connectionType === "sampleClip" ? camera.sampleClipPath : undefined,
    targetSec: 300,
    sessionId,
    cameraId: camera.id,
    cameraLabel: camera.label,
  }).catch((err) => {
    console.error(`[cloud] scheduled send failed for ${camera.label}: ${err.message}`);
    logEvent("pipeline_failed", `${camera.label} scheduled upload failed`, err.message);
  });
}

async function processCommands() {
  const connection = getCloudConnection();
  if (!connection) return;
  const commands = await fetchPendingCommands(connection);
  // Sequential, not Promise.all -- two commands for the same camera
  // arriving in one batch (e.g. a fast double-click before the console's
  // own button re-renders) should apply in order, not race.
  for (const command of commands) {
    try {
      const result = await runCommand(command);
      await completeCommand(connection, command.id, "done", result);
    } catch (err) {
      await completeCommand(connection, command.id, "error", { error: err.message });
    }
  }
}

// Runs the same pending-commands pass the heartbeat tick does, on demand.
//
// Debounced because the realtime channel fires per inserted row: the
// console sending two commands at once would otherwise start two
// overlapping passes, and processCommands() is deliberately sequential.
let commandsRunning = null;
let commandsQueued = false;

export async function processCommandsNow() {
  if (commandsRunning) {
    commandsQueued = true; // something arrived mid-pass; sweep again after
    return commandsRunning;
  }
  commandsRunning = (async () => {
    try {
      await processCommands();
    } finally {
      commandsRunning = null;
      if (commandsQueued) {
        commandsQueued = false;
        await processCommandsNow();
      }
    }
  })();
  return commandsRunning;
}

export function startHeartbeatLoop() {
  if (heartbeatTimer) return; // already running
  if (!getCloudConnection()) return;
  const tick = async () => {
    // processCommands() first, not sendHeartbeat() -- a command executed
    // this tick (e.g. start_recording) changes local state (isRecording())
    // that cameraStatuses() reads; running the heartbeat first would report
    // the *old* state and make the console wait a full extra cycle to see
    // a change that already happened this tick.
    await processCommandsNow();
    sendHeartbeat(); // don't wait a full interval for the first "online" signal
  };
  tick();
  heartbeatTimer = setInterval(tick, HEARTBEAT_INTERVAL_MS);
}

export function stopHeartbeatLoop() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}
