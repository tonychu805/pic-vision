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
import { listCameras, testConnection, setCameraProfile, onCamerasChanged } from "./cameras/store.js";
import { classifyProbeError, describeProbeState } from "./cameras/probeResult.js";
import { isRecording, listRecordings, startRecording, stopRecording, measureStreamFps, measureStreamProfile, authenticatedStreamUri } from "./capture.js";
import { grabAndUploadSnapshot } from "./calibration.js";
import { basename } from "node:path";
import { runCloudJob } from "./pipeline.js";
import { logEvent } from "./activityLog.js";
import { encryptField, decryptField } from "./secureField.js";
import { isCommandChannelLive } from "./commandChannel.js";
import { withDeadline } from "./deadline.js";

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

// 30s until 2026-09-20. Each tick costs TWO cloud-function calls (the
// command sweep below and the heartbeat itself), so one always-on agent
// was ~173k calls a month before a single venue recorded anything --
// which, with the job runner's own idle poll, is what exhausted the
// Netlify quota and took every public site down for five days.
//
// PAIRED with the console's OFFLINE_AFTER_MS (overview-client.tsx),
// which is three of these: raising one without the other would show
// every agent permanently offline. They are changed together, and the
// comment there says so too.
export const HEARTBEAT_INTERVAL_MS = 60_000;

// Every wait in the heartbeat and command paths has a limit (2026-09-21).
// Before, a single call that never settled froze the whole command pass, and
// the tick awaited that pass before sending its heartbeat, so the console
// heard nothing while the app still said "Connected" -- a hang is not a
// failure, so nothing was ever logged. See deadline.js.
//
// A camera on the venue's own LAN answers in well under a second; this is
// generous, and past it the camera is reported offline like any other failed
// probe rather than holding every other camera's status hostage.
const PROBE_DEADLINE_MS = 20_000;
// One small JSON round trip to the console.
const CONSOLE_REQUEST_TIMEOUT_MS = 30_000;
// A single command (grab a frame and upload it, start/stop recording). Long
// enough for a slow upload of one still, short enough that one stuck command
// cannot hold the queue for the rest of the session.
const COMMAND_DEADLINE_MS = 120_000;
// How long a tick waits for the command pass before sending its heartbeat
// anyway. Commands still get first go in the ordinary case (see the tick for
// why), but a stuck pass must not be able to silence the heartbeat.
const SWEEP_WAIT_MS = 15_000;

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

// Transition-tracking for the activity log -- a camera starts undefined
// ("no prior reading yet") so the very first reading doesn't log a
// spurious "recovered" the moment it succeeds; only an actual change from
// a previously-known state logs anything.
const lastCameraStatus = new Map(); // cameraId -> "online" | "offline"

// PIC-92. This was `lastHeartbeatOk = true` -- initialised true purely so
// the first successful tick wouldn't log a false "reconnected". That made
// it unusable as something to SHOW: before the first tick it means
// "assumed fine", and "assumed fine" rendered as "Connected" is exactly
// the lie this ticket is about. Three states instead of two:
//
//   null  -- no attempt has completed yet. Not connected, not broken:
//            unknown, and the UI says so rather than picking one.
//   true  -- the most recent attempt succeeded.
//   false -- the most recent attempt failed.
//
// The log transitions come out identical to the old boolean (a first-ever
// failure still logs "lost", a first-ever success still logs nothing),
// which is why there is one variable here and not two.
let lastAttemptOk = null;

// When a heartbeat last actually SUCCEEDED, so a failure can say how long
// the connection has really been down instead of just "lost". Stays null
// until one succeeds -- a connection that has never once checked in is a
// different thing from one that checked in an hour ago, and the operator
// needs to tell them apart.
let lastHeartbeatAt = null;

/**
 * What the Cloud page shows instead of "is a connection stored locally".
 *
 * Deliberately carries no error text: why a heartbeat failed is already
 * logged (with its HTTP status or message) to the Log tab, and raw thrown
 * text reaching the UI is the exact defect PIC-93 and PIC-144 were about.
 * The renderer gets state, not a message it would be tempted to print.
 */
export function getHeartbeatState() {
  return { lastAttemptOk, lastHeartbeatAt };
}

// Calibration state as last reported by the console (ADR-084 -- the
// console owns it now, there's no local calib.json anymore). Refreshed on
// every heartbeat response; read by main.js's cameras:list so the UI can
// show it and gate "send to cloud" on it. Empty until the first heartbeat
// lands, which reads as "not calibrated yet" -- correct for an unpaired
// or freshly-launched agent.
const calibrationByCameraId = new Map(); // cameraId -> { isCalibrated, calibrationRmseFt, calibratedAt }

// The other machines this venue has, by name, from the same heartbeat
// response. Only used to warn before someone names two machines the same
// thing: nothing enforces uniqueness (identity is the agent id), so a
// duplicate breaks nothing technically -- it breaks the console's own
// Cameras/Schedule/Reels pages, which show this name to tell two venues'
// "Court 1"s apart. Empty until the first heartbeat lands, which reads as
// "no known clash" -- the right default for a warning.
let otherAgentNames = [];

export function getOtherAgentNames() {
  return otherAgentNames;
}

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
  // Push the rename now rather than at the next interval. Through the shared
  // runner (see runHeartbeat) so it cannot overlap a heartbeat already in
  // flight -- the same out-of-order hazard the camera list has.
  runHeartbeat({ rerunIfBusy: true });
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

// Found live, and the reason this exists at all (PIC-93): a bare network
// failure surfaced as "Error invoking remote method 'cloud:register':
// TypeError: fetch failed" -- meaningless to a venue operator, useless
// even to a technical one without also knowing the URL it failed against
// (which the earlier version discarded along with everything else).
//
// The three throw sites below use short, deliberate sentinel messages
// ("network"/"auth"/"server") instead of whatever the real failure said --
// contract with src/lib/ipcError.js's describeRegisterError, which maps
// each to a plain sentence CloudPage shows, the same "classify near the
// source, translate at the edge" split probeResult.js already established
// for camera failures (PIC-93's own resolution note names that as the
// pattern to copy). The real text isn't lost, just moved: logEvent puts it
// in the Log tab, exactly where a raw camera error already goes.
//
// No timeout on this fetch until now, either -- an unreachable console (a
// host that accepts the connection but never answers, or a network that
// drops the packets silently rather than refusing) left it to whatever
// Node's own default eventually gives up at, long enough that
// "Connecting…" on the button had no real ceiling. Same fix, same
// reasoning, as rtspProbe.js's connect-phase timeout from earlier today --
// found here by this fix's own test hanging past the harness's 300s
// budget against exactly that shape of failure.
const REGISTER_TIMEOUT_MS = 20_000;

// Exported, and timeoutMs is a parameter rather than only the module
// constant above, for cloud.test.js: the classification is worth pinning
// directly against a real local HTTP server (same reasoning
// bandwidth.test.js's own withServer already uses -- a mocked request
// object would only prove the mock), and a test exercising the timeout
// path needs milliseconds, not 20 real seconds, to prove the mechanism
// without a slow test run.
//
// registerAgent() above is still the only real entry point that adds the
// single-flight guard on top of this -- but a successful call through
// EITHER one starts the heartbeat loop (see the tail of this function), so
// a test exercising the success path has to stop that loop again, or the
// interval it creates keeps the process alive indefinitely. Found exactly
// that way: the happy-path test hung past the harness's whole budget with
// no failing assertion anywhere, because the test itself had already
// passed by the time the leftover interval kept running.
export async function registerAgentOnce(accessToken, userId, consoleUrl, timeoutMs = REGISTER_TIMEOUT_MS) {
  let res;
  try {
    res = await fetch(`${consoleUrl}/api/agents/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ deviceId: getOrCreateDeviceId(), agentName: getAgentName() }),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    // A timeout (AbortError/TimeoutError) and a real connection failure
    // both mean the same thing to an operator -- the console couldn't be
    // reached -- so both fall into the same "network" bucket rather than
    // needing their own message.
    logEvent("cloud_register_failed", "Couldn't reach the cloud console to connect this machine",
      `${consoleUrl}: ${err.message}`);
    throw new Error("network");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    // 5xx here is very often a raw Postgres error string in body.error
    // (the console API's own known gap, PIC-144) -- never shown as-is
    // regardless of what it says, only ever "server" plus the real text
    // kept in the Log tab. 4xx (not signed in / session expired / this
    // device's local state is wrong somehow) is real, addressable text
    // from the console, and IS worth keeping close to verbatim -- so it
    // goes to the log too, but classified as "auth" for the plain-language
    // side rather than folded into the same generic bucket as a 500.
    logEvent("cloud_register_failed", "Connecting this machine to the cloud console failed",
      `HTTP ${res.status}: ${body.error || "(no error body)"}`);
    throw new Error(res.status >= 500 ? "server" : "auth");
  }

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
  // Fresh connection: back to "not checked yet", so a stale prior failure
  // can't log a false "reconnected" on the first tick AND the page doesn't
  // claim a working link before one heartbeat has proved it (PIC-92).
  lastAttemptOk = null;
  lastHeartbeatAt = null;
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
  // Otherwise a later reconnection inherits this one's health, and the
  // page could show a "last check-in" belonging to a connection that no
  // longer exists.
  lastAttemptOk = null;
  lastHeartbeatAt = null;
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
  const results = await Promise.allSettled(cameras.map((c) => withDeadline(testConnection(c), PROBE_DEADLINE_MS, `Checking ${c.label}`)));
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

export async function sendHeartbeat(timeoutMs = CONSOLE_REQUEST_TIMEOUT_MS) {
  const connection = getCloudConnection();
  if (!connection) return;

  const cameras = await cameraStatuses();
  try {
    const res = await fetch(`${connection.consoleUrl}/api/agents/heartbeat`, {
      signal: AbortSignal.timeout(timeoutMs),
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${connection.apiToken}` },
      body: JSON.stringify({ cameraCount: cameras.length, cameras, agentName: getAgentName() }),
    });
    if (!res.ok) {
      // A rejected token (e.g. the agent row was deleted server-side)
      // isn't retried forever -- surfaces in status() instead of
      // silently hammering an endpoint that will never accept it again.
      console.error(`[cloud] heartbeat rejected: HTTP ${res.status}`);
      if (lastAttemptOk !== false) logEvent("cloud_disconnected", "Lost connection to the cloud console", `HTTP ${res.status}`);
      lastAttemptOk = false;
      return;
    }
    if (lastAttemptOk === false) logEvent("cloud_connected", "Reconnected to the cloud console");
    lastAttemptOk = true;
    lastHeartbeatAt = new Date().toISOString();
    // Keeps a Settings-page rename on the console reaching this already-
    // paired agent within one heartbeat cycle, instead of only ever
    // reflecting whatever the brand was named at pairing time.
    const body = await res.json().catch(() => ({}));
    if (typeof body.brandName === "string" && body.brandName !== connection.brandName) {
      saveConnection({ ...connection, brandName: body.brandName });
    }
    if (Array.isArray(body.otherAgentNames)) {
      otherAgentNames = body.otherAgentNames.filter((n) => typeof n === "string");
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
    if (lastAttemptOk !== false) logEvent("cloud_disconnected", "Lost connection to the cloud console", err.message);
    lastAttemptOk = false;
  }
}

// ---- Heartbeats that never overlap, and one that can be asked for now ----
//
// A heartbeat carries the whole camera list, and the console prunes any
// camera that isn't in it. Two in flight at once can therefore arrive out of
// order: an older snapshot that still contains a just-removed camera landing
// AFTER the newer one would re-insert it. So every heartbeat -- the regular
// tick and the ones asked for below -- goes through one runner that allows
// exactly one at a time.
//
// A request that arrives while one is already running sets a flag instead of
// being dropped. The running heartbeat may have taken its snapshot of the
// camera list before the change, so it can't be trusted to include it; a
// second run after it finishes can.
let heartbeatInFlight = null;
let heartbeatRerun = false;

function runHeartbeat({ rerunIfBusy = false } = {}) {
  if (heartbeatInFlight) {
    if (rerunIfBusy) heartbeatRerun = true;
    return heartbeatInFlight;
  }
  heartbeatInFlight = (async () => {
    try {
      do {
        heartbeatRerun = false;
        try {
          await sendHeartbeat();
        } catch (err) {
          // sendHeartbeat handles a failed POST itself; this is for the
          // part before it, probing the cameras. Never let it escape: the
          // caller is a timer or a fire-and-forget request.
          console.error(`[cloud] heartbeat crashed: ${err.message}`);
        }
      } while (heartbeatRerun);
    } finally {
      heartbeatInFlight = null;
    }
  })();
  return heartbeatInFlight;
}

// Collapses a burst -- adding four cameras in a row, or removing several --
// into one heartbeat. Long enough to catch a burst, short enough that the
// console still hears about a single change within a second or so.
export const HEARTBEAT_DEBOUNCE_MS = 400;
let heartbeatDebounce = null;

/**
 * Tell the console about a change to the camera list now, rather than at the
 * next timer tick. Fire-and-forget: the operator's click never waits on it.
 *
 * A heartbeat probes every camera before it posts, so "now" is as fast as the
 * slowest probe -- a few seconds, not the interval. That is the cost of
 * sending a truthful list; the alternative is reporting a status this machine
 * has not just checked.
 */
export function requestHeartbeat() {
  // Not connected means nothing to tell. sendHeartbeat would return at once
  // anyway; skipping here also avoids arming a timer for nothing.
  if (!getCloudConnection()) return;
  if (heartbeatDebounce) return;
  heartbeatDebounce = setTimeout(() => {
    heartbeatDebounce = null;
    runHeartbeat({ rerunIfBusy: true });
  }, HEARTBEAT_DEBOUNCE_MS);
  // Never the thing keeping the process alive.
  heartbeatDebounce.unref?.();
}

// Wired here, not in main.js, so every path that changes the camera list is
// covered by construction -- including ones added later.
onCamerasChanged(requestHeartbeat);

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
      signal: AbortSignal.timeout(CONSOLE_REQUEST_TIMEOUT_MS),
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
      signal: AbortSignal.timeout(CONSOLE_REQUEST_TIMEOUT_MS),
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
    targetSec: 180,
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
      const result = await withDeadline(runCommand(command), COMMAND_DEADLINE_MS, command.type);
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
    //
    // Skipped entirely while the Realtime push channel is connected
    // (2026-09-20). Commands already arrive over that websocket, which
    // costs nothing per message and is what makes "Calibrate" feel
    // instant; this sweep is the fallback commandChannel.js's own header
    // describes, for a dropped socket or Realtime being down. Running it
    // anyway doubled every agent's cloud-function usage to buy nothing.
    // Deliberately "is the channel live right now", not "was it ever" --
    // a socket that drops mid-session must bring the fallback back.
    //
    // Bounded (2026-09-21): a pass that never finishes used to hold this tick
    // -- and with it the heartbeat -- forever, while the app went on saying
    // "Connected". The pass still gets its head start; it just cannot keep
    // the heartbeat waiting past SWEEP_WAIT_MS.
    if (!isCommandChannelLive()) await withDeadline(processCommandsNow(), SWEEP_WAIT_MS, "command sweep").catch(() => {});
    runHeartbeat(); // don't wait a full interval for the first "online" signal
  };
  tick();
  heartbeatTimer = setInterval(tick, HEARTBEAT_INTERVAL_MS);
}

export function stopHeartbeatLoop() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}
