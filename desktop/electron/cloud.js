// First real outbound connectivity from the local agent to the cloud
// console (ADR-071's "polls or a lightweight persistent connection for
// commands/status, never an inbound port"). Pairing + a heartbeat that
// also reports the real camera list (2026-09-03). Reel reporting (ADR-074,
// 2026-09-04) is a separate one-shot POST from cloud_pipeline/
// run_desktop_job.py, not part of this heartbeat. Schedule migrated to
// the cloud console entirely the same day (ADR-071/PIC-73) -- no local
// schedule.js left to report on. Same electron-store-per-concern
// convention as cameras/store.js.
import { randomUUID } from "node:crypto";
import { hostname } from "node:os";
import Store from "electron-store";
import { listCameras, testConnection } from "./cameras/store.js";
import { isRecording, listRecordings, startRecording, stopRecording } from "./capture.js";
import { grabAndUploadSnapshot, applyPendingCalibration } from "./calibration.js";
import { logEvent } from "./activityLog.js";

const store = new Store({ name: "cloud" });

// Overridable for local dev (the console runs on localhost:3000 via
// `pnpm dev` before it's deployed anywhere) without hardcoding either URL
// as the only option.
const DEFAULT_CONSOLE_URL = process.env.PIC_VISION_CLOUD_URL || "http://localhost:3000";

const HEARTBEAT_INTERVAL_MS = 30_000;

let heartbeatTimer = null;

// Transition-tracking for the activity log -- both start "assumed fine"
// (undefined for a camera means "no prior reading yet," true for the
// heartbeat means "just connected/registered") so the very first
// heartbeat tick after a launch or a fresh registration doesn't log a
// spurious "recovered" the moment it succeeds; only an actual change from
// a previously-known state logs anything.
const lastCameraStatus = new Map(); // cameraId -> "online" | "offline"
let lastHeartbeatOk = true;

export function getCloudConnection() {
  return store.get("connection", null);
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
// The returned long-lived API token is stored locally the same way camera
// passwords already are (cameras/store.js's electron-store JSON -- see
// that file's header for why this is a known, already-flagged POC gap,
// not a new one introduced here).
export async function registerAgent(accessToken, consoleUrl = DEFAULT_CONSOLE_URL) {
  const res = await fetch(`${consoleUrl}/api/agents/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ deviceId: getOrCreateDeviceId(), agentName: getAgentName() }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `device registration failed (HTTP ${res.status})`);

  const connection = {
    consoleUrl,
    agentId: body.agentId,
    apiToken: body.apiToken,
    brandName: body.brandName,
    connectedAt: new Date().toISOString(),
  };
  store.set("connection", connection);
  lastHeartbeatOk = true; // fresh connection -- don't let a stale prior failure log a false "reconnected" on the first tick
  logEvent("cloud_connected", `Connected to the cloud console (${body.brandName})`);
  startHeartbeatLoop();
  return connection;
}

export function disconnectCloud() {
  stopHeartbeatLoop();
  store.delete("connection");
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
    const previous = lastCameraStatus.get(c.id);
    if (previous && previous !== status) {
      logEvent(status === "online" ? "camera_online" : "camera_offline", `${c.label} ${status === "online" ? "came back online" : "went offline"}`);
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
      isCalibrated: Boolean(c.calibPath),
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
      store.set("connection", { ...connection, brandName: body.brandName });
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
  if (command.type === "stop_recording") return await stopRecording(camera.id);
  // Console-driven calibration (ADR-080) -- see calibration.js's header
  // for why this replaced ADR-077's "scoped out" call on moving it here.
  if (command.type === "grab_calibration_snapshot") return await grabAndUploadSnapshot(camera);
  if (command.type === "apply_calibration") return applyPendingCalibration(camera, command.params?.points);
  throw new Error(`unknown command type: ${command.type}`);
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

export function startHeartbeatLoop() {
  if (heartbeatTimer) return; // already running
  if (!getCloudConnection()) return;
  const tick = async () => {
    // processCommands() first, not sendHeartbeat() -- a command executed
    // this tick (e.g. start_recording) changes local state (isRecording())
    // that cameraStatuses() reads; running the heartbeat first would report
    // the *old* state and make the console wait a full extra cycle to see
    // a change that already happened this tick.
    await processCommands();
    sendHeartbeat(); // don't wait a full interval for the first "online" signal
  };
  tick();
  heartbeatTimer = setInterval(tick, HEARTBEAT_INTERVAL_MS);
}

export function stopHeartbeatLoop() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}
