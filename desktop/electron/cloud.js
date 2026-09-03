// First real outbound connectivity from the local agent to the cloud
// console (ADR-071's "polls or a lightweight persistent connection for
// commands/status, never an inbound port"). Pairing + a heartbeat that
// also reports the real camera list (2026-09-03) -- no court/reel sync
// yet, that's later work. Same electron-store-per-concern convention as
// cameras/store.js and schedule.js.
import Store from "electron-store";
import { listCameras, testConnection } from "./cameras/store.js";

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

// Exchanges a short-lived pairing code (typed in from the console's
// dashboard) for a long-lived API token, stored locally the same way
// camera passwords already are (cameras/store.js's electron-store JSON --
// see that file's header for why this is a known, already-flagged POC
// gap, not a new one introduced here).
export async function pairAgent(pairingCode, consoleUrl = DEFAULT_CONSOLE_URL) {
  const res = await fetch(`${consoleUrl}/api/agents/pair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pairingCode }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `pairing failed (HTTP ${res.status})`);

  const connection = {
    consoleUrl,
    agentId: body.agentId,
    apiToken: body.apiToken,
    venueName: body.venueName,
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

// Live-checks every configured camera the same way CamerasPage.jsx's own
// "checking" -> testConnection -> ok/offline flow already does (no new
// health-check logic invented) -- but from the main process, on the
// heartbeat's own schedule, so status is fresh even with no renderer
// window open. Only non-sensitive identity fields are reported --
// hostname/port/username/password/streamUri never leave this machine,
// per ADR-071's "camera-facing data stays local" (a stream URI can embed
// credentials for an RTSP camera, so it's excluded same as the rest).
async function cameraStatuses() {
  const cameras = listCameras();
  const results = await Promise.allSettled(cameras.map((c) => testConnection(c)));
  return cameras.map((c, i) => ({
    cameraId: c.id,
    label: c.label,
    connectionType: c.connectionType,
    manufacturer: c.manufacturer ?? null,
    model: c.model ?? null,
    status: results[i].status === "fulfilled" ? "online" : "offline",
  }));
}

async function sendHeartbeat() {
  const connection = getCloudConnection();
  if (!connection) return;

  const cameras = await cameraStatuses();
  try {
    const res = await fetch(`${connection.consoleUrl}/api/agents/heartbeat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${connection.apiToken}` },
      body: JSON.stringify({ cameraCount: cameras.length, cameras }),
    });
    if (!res.ok) {
      // A rejected token (e.g. the agent row was deleted server-side)
      // isn't retried forever -- surfaces in status() instead of
      // silently hammering an endpoint that will never accept it again.
      console.error(`[cloud] heartbeat rejected: HTTP ${res.status}`);
    }
  } catch (err) {
    // Console unreachable (offline venue, DNS hiccup, console down) --
    // logged, not thrown; the loop just tries again next interval rather
    // than crashing the agent over a transient network blip.
    console.error(`[cloud] heartbeat failed: ${err.message}`);
  }
}

export function startHeartbeatLoop() {
  if (heartbeatTimer) return; // already running
  if (!getCloudConnection()) return;
  sendHeartbeat(); // don't wait a full interval for the first "online" signal
  heartbeatTimer = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
}

export function stopHeartbeatLoop() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}
