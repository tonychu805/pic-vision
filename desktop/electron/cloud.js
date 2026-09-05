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

const store = new Store({ name: "cloud" });

// Overridable for local dev (the console runs on localhost:3000 via
// `pnpm dev` before it's deployed anywhere) without hardcoding either URL
// as the only option.
const DEFAULT_CONSOLE_URL = process.env.PIC_VISION_CLOUD_URL || "http://localhost:3000";

const HEARTBEAT_INTERVAL_MS = 30_000;

let heartbeatTimer = null;

export function getCloudConnection() {
  return store.get("connection", null);
}

// A stable identity for this machine, independent of pairing state --
// generated once and kept even across disconnectCloud() (unlike
// "connection", which is cleared there). Without this, every re-pair
// (including a retried/failed attempt against the wrong URL) minted a
// brand-new `agents` row server-side with no way to recognize "this is
// the same desktop as before" -- duplicate agents *and* duplicate
// cameras, since camera-heartbeat sync just re-inserts under whatever
// agent_id the current token maps to. The pair endpoint uses this to
// reclaim the existing row for this device instead.
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
// rather than only at pairing time, so a rename takes effect within one
// interval without needing to re-pair.
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

// Exchanges a short-lived pairing code (typed in from the console's
// dashboard) for a long-lived API token, stored locally the same way
// camera passwords already are (cameras/store.js's electron-store JSON --
// see that file's header for why this is a known, already-flagged POC
// gap, not a new one introduced here).
export async function pairAgent(pairingCode, consoleUrl = DEFAULT_CONSOLE_URL) {
  const res = await fetch(`${consoleUrl}/api/agents/pair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pairingCode, deviceId: getOrCreateDeviceId() }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `pairing failed (HTTP ${res.status})`);

  const connection = {
    consoleUrl,
    agentId: body.agentId,
    apiToken: body.apiToken,
    brandName: body.brandName,
    pairedAt: new Date().toISOString(),
  };
  store.set("connection", connection);
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
    return {
      cameraId: c.id,
      label: c.label,
      connectionType: c.connectionType,
      manufacturer: c.manufacturer ?? null,
      model: c.model ?? null,
      status: results[i].status === "fulfilled" ? "online" : "offline",
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
      return;
    }
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
  }
}

// First real use of the cloud->agent command channel (ADR-071/ADR-073's
// long-flagged missing piece): the console can now create a row in
// `agent_commands` (POST /api/commands, e.g. the Cameras page's Start/
// Stop recording button) and this picks it up here, on the *same*
// heartbeat cadence -- no separate timer, no persistent connection,
// consistent with ADR-071's "polling is fine, none of this is
// latency-sensitive like live video" call. Recording itself still has to
// run wherever the camera actually is, so this just calls the exact same
// capture.js functions the desktop app's own Start/Stop button already
// calls -- only the trigger moved, not the action.
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
  if (camera.connectionType === "sampleClip") {
    throw new Error("sample-clip cameras have no live stream to record");
  }
  if (command.type === "start_recording") return await startRecording(camera);
  if (command.type === "stop_recording") return await stopRecording(camera.id);
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
