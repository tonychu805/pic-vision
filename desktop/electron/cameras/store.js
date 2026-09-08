// Persisted list of cameras the venue owner has added (manually, or kept
// from a discovery result), plus the connect/describe logic both the
// "add camera" and "test connection" UI actions need.
//
// password/streamUri are OS-vault-encrypted at rest (see secureField.js,
// PIC-79) where the OS actually provides one -- on a machine with no
// vault available (e.g. a headless Linux box with no keyring daemon),
// they fall back to the plain JSON this file originally shipped with.
// STRATEGY.md §5's RunPod/R2 credentials gap is the same class of
// problem but a separate, not-yet-built fix (server-side secrets, not a
// local electron-store field).
import Store from "electron-store";
// See discovery.js for why this is a default import + destructure, not a
// named import, despite onvif/promises being ESM-consumed CJS.
import onvifPromises from "onvif/promises/index.js";
const { Cam } = onvifPromises;
import { randomUUID } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { findWorkingRtspPath, describeRtspStream } from "./rtspProbe.js";
import { vendorsForIps } from "./vendorLookup.js";
import { RECORDINGS_ROOT, sanitizeForPath, measureStreamFps, measureStreamProfile, authenticatedStreamUri } from "../capture.js";
import { encryptField, decryptField } from "../secureField.js";

// configFileMode 0600: owner-only, and set here rather than chmod-ed
// afterwards -- see activityLog.js for why that distinction matters.
const store = new Store({ name: "cameras", configFileMode: 0o600 });

// password and streamUri (the RTSP-direct fallback embeds credentials
// directly in the URL, see addCameraViaRtsp below) are the only fields
// here that are actual secrets -- everything else (hostname, label,
// manufacturer) is metadata safe to leave in the clear. Centralized here
// rather than at each call site: every mutator already builds its full
// camera list in memory and calls store.set once, so encrypting on the
// way into that one call and decrypting on the way out of listCameras
// covers every reader/writer in this file for free.
function encryptCamera(camera) {
  return { ...camera, password: encryptField(camera.password), streamUri: encryptField(camera.streamUri) };
}
function decryptCamera(camera) {
  return { ...camera, password: decryptField(camera.password), streamUri: decryptField(camera.streamUri) };
}

// What the renderer is allowed to see (PIC-97, 2026-09-06).
//
// ADR-082 encrypted `password` and `streamUri` at rest with the OS vault,
// and then `cameras:list` handed both back decrypted on every page load --
// so the encryption protected the disk and nothing else. Anyone who could
// open the app, or its DevTools, could read every camera password at a
// venue. That was tolerable while this only ran on the operator's own
// machine; it stops being tolerable the moment there's an installer.
//
// `password` is dropped outright: no screen needs it. `streamUri` is
// redacted rather than dropped because the Streams panel is a real
// troubleshooting aid -- but the RTSP-direct fallback embeds credentials
// in that URI (see addCameraViaRtsp), so what the UI displays now has
// them starred out. `revealStreamUri()` below returns the real thing for
// the Copy button, which makes exposing it a deliberate act rather than
// something that happens on every render.
export function redactStreamUri(uri) {
  if (typeof uri !== "string" || !uri) return uri ?? null;
  // rtsp://user:pass@host/path -> rtsp://***:***@host/path. Deliberately
  // keeps the shape so "does this camera need credentials" stays visible.
  //
  // [^/]* rather than [^/@]+: an @ inside the password is legal and does
  // happen, and stopping at the FIRST @ left the tail of it on screen
  // ("rtsp://***:***@ss@10.0.0.5"). Greedy up to the last @ before the
  // path instead. Caught by redaction.test.js, which is why that case is
  // in there.
  return uri.replace(/:\/\/[^/]*@/, "://***:***@");
}

export function publicCamera(camera) {
  if (!camera) return camera;
  const { password: _password, ...rest } = camera;
  return { ...rest, streamUri: redactStreamUri(camera.streamUri) };
}

// The full stream URI, credentials included, for one camera. Only reached
// by an explicit "Copy" in the UI -- never by a list render.
export function revealStreamUri(cameraId) {
  const camera = listCameras().find((c) => c.id === cameraId);
  return camera?.streamUri ?? null;
}

export function listCameras() {
  return store.get("cameras", []).map(decryptCamera);
}

// Puts back the secrets the renderer never had.
//
// The renderer round-trips camera objects: it calls cameras:list, holds
// the result, and hands one back to cameras:testConnection. Since
// publicCamera() started stripping `password` (ADR-088), that round trip
// arrived in main with no credentials, so every configured camera failed
// its own status check with a 401 -- reported 2026-09-07 as "why do my
// cameras suddenly need signing in, when live view still works?".
//
// Live view never broke because it takes a camera ID and looks the real
// camera up here (main.js's liveview:start). That's the safer shape, and
// this makes the object-taking handlers behave the same way: if what came
// in names a camera we have stored, the stored one wins.
//
// Deliberately merge rather than replace outright, so an unsaved camera
// being tested during the add flow (no id yet) still works untouched.
export function withStoredSecrets(config) {
  if (!config?.id) return config;
  const stored = listCameras().find((c) => c.id === config.id);
  return mergeStoredSecrets(config, stored);
}

// The merge itself, split out so a test can prove the ROUND TRIP without
// an Electron store to seed: publicCamera() strips, this restores, and the
// result must be usable again. That pairing is the assertion the original
// redaction tests were missing -- they proved the password was gone (true,
// and the app was broken) but never that anything still worked without it.
export function mergeStoredSecrets(config, stored) {
  if (!config || !stored) return config;
  return {
    ...config,
    // FILL a gap, don't overwrite. The first version replaced both fields
    // unconditionally, which is a trap rather than a bug today: nothing
    // currently sends fresh credentials through a handler that calls this.
    // But "verify these before I save them" is the obvious next button to
    // build, and routed through cameras:testConnection it would have had
    // the typed password swapped for the stored one, passed against the
    // OLD credentials, and told the operator the new ones work.
    password: config.password ?? stored.password,
    // streamUri needs the opposite default. publicCamera() DROPS the
    // password but only STARS the URI, so the renderer's copy is a
    // present, plausible-looking, unusable string -- `??` would happily
    // keep "rtsp://***:***@host/stream1". Anything still bearing the
    // redaction marker is the renderer's copy and must be replaced.
    streamUri: isRedactedStreamUri(config.streamUri) || config.streamUri == null ? stored.streamUri : config.streamUri,
  };
}

// The marker redactStreamUri() leaves behind. Kept next to it so the two
// can't drift apart: if that starring changes shape, this must too.
function isRedactedStreamUri(uri) {
  return typeof uri === "string" && uri.includes("://***:***@");
}

// The list the renderer gets. listCameras() stays internal: capture.js,
// heartbeats and testConnection all genuinely need the real credentials.
export function listCamerasForRenderer() {
  return listCameras().map(publicCamera);
}

function saveCameras(cameras) {
  store.set("cameras", cameras.map(encryptCamera));
}

export async function testConnection({ hostname, port, username, password, path: connectPath, connectionType, sampleClipPath }) {
  // A sample-clip "camera" has no network connection to test at all --
  // the closest equivalent check is just confirming its one video file is
  // still where it was left (it could have been moved/deleted outside the
  // app since being added).
  if (connectionType === "sampleClip") {
    if (!sampleClipPath || !existsSync(sampleClipPath)) throw new Error("Sample clip file is missing");
    return { info: {}, streamUri: null };
  }

  // Stored cameras carry their own connectionType ('onvif' or 'rtsp',
  // added by addCamera/addCameraViaRtsp) -- an RTSP-direct camera has no
  // ONVIF service to test against at all, so the periodic status check
  // (CamerasPage.jsx) needs to actually probe the way it was added, not
  // always assume ONVIF. Absent (the ONVIF add flow's own internal
  // pre-save check, before anything is stored) defaults to ONVIF, same as
  // before this branch existed.
  if (connectionType === "rtsp") {
    await describeRtspStream({ hostname, port: port || 554, path: connectPath, username, password });
    return { info: {}, streamUri: null };
  }

  // connectPath defaults to the library's own '/onvif/device_service' when
  // omitted -- but that's not universal. A real Synology camera on this
  // network (2026-09-01) serves ONVIF at '/Onvif/device_service' (capital
  // O) instead, confirmed via a raw HTTP probe (401 + WWW-Authenticate:
  // Digest realm="IPCam" there, plain 404 at the lowercase path) -- WS-
  // Discovery never found it either, so manual add is the only way in,
  // and it needs this override to actually reach the right endpoint.
  const cam = new Cam({ hostname, port: port || 80, username, password, path: connectPath || undefined });
  await cam.connect();
  const info = await cam.getDeviceInformation();
  let streamUri = null;
  try {
    streamUri = (await cam.getStreamUri({ protocol: "RTSP" })).uri;
  } catch {
    // Some devices need a profile token before they'll hand back a stream
    // URI -- connection itself already succeeded, so don't fail the whole
    // test over this.
  }
  return { info, streamUri, profile: streamProfile(cam) };
}

// What the camera is actually about to send us: codec, resolution, frame
// rate and bitrate. This costs no extra network round-trip -- connect()
// already calls getProfiles() internally and populates `activeSource` from
// the same default profile that getStreamUri() above resolves to; the
// values were simply being thrown away.
//
// Worth recording because the pipeline's behaviour depends on all four and
// none of them were previously visible:
//   - codec: H.265 is increasingly the factory default, and this project has
//     already lost a session to HEVC damage that made the decoder stop
//     silently (930 of 121,013 frames, exit code 0 -- see EXPERIMENTS.md
//     2026-08-16). Knowing which venues stream H.265 is the difference
//     between predicting that and discovering it.
//   - frame rate: the ball tracker's max-jump threshold assumes how far a
//     ball can travel between two frames, so a 15fps camera moves the ball
//     twice as far per frame as the tuning expects.
//   - resolution/bitrate: what the venue's upload actually costs, which is
//     set here in the camera, not by anything downstream.
function streamProfile(cam) {
  const source = cam.activeSource;
  if (!source) return null;
  const toNumber = (v) => {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : null;
  };
  return {
    codec: source.encoding ? String(source.encoding).toUpperCase() : null,
    width: toNumber(source.width),
    height: toNumber(source.height),
    fps: toNumber(source.fps),
    bitrateKbps: toNumber(source.bitrate),
  };
}

// Shapes a measured profile the way the ONVIF path stores one: `fps` is
// reserved for the camera's *configured* rate, which nothing can tell us
// here, so the measured rate lands in `measuredFps` and `fps` stays null.
async function rtspProfile(uri) {
  const measured = await measureStreamProfile(uri);
  if (!measured) return { codec: null, width: null, height: null, fps: null, measuredFps: null, bitrateKbps: null };
  const { fps, ...rest } = measured;
  return { ...rest, fps: null, measuredFps: fps };
}

// Real duplicate found 2026-09-01: the same physical Synology camera got
// added twice (two independent `addCamera` calls a few seconds apart,
// same hostname, no cross-check between them) -- neither addCamera nor
// addCameraViaRtsp had ever refused or noticed a hostname that was
// already configured. Idempotent by hostname now: a second add for an
// already-configured hostname just returns the existing entry rather
// than re-verifying and creating a duplicate -- the camera was already
// verified when it was first added, so there's nothing to re-check.
function existingByHostname(hostname) {
  return listCameras().find((c) => c.hostname === hostname);
}

export async function addCamera({ label, hostname, port, username, password, path }) {
  const existing = existingByHostname(hostname);
  if (existing) return existing;
  const { info, streamUri, profile } = await testConnection({ hostname, port, username, password, path });
  const camera = {
    id: randomUUID(),
    label: label || info.manufacturer + " " + info.model,
    hostname,
    port: port || 80,
    path: path || undefined,
    username,
    password,
    manufacturer: info.manufacturer,
    model: info.model,
    // ONVIF's GetDeviceInformation doesn't return a MAC address -- there's
    // no real value to put here (see DiscoveryPanel/CameraDetailPage,
    // which render "Not available" rather than a fabricated one).
    serialNumber: info.serialNumber,
    firmwareVersion: info.firmwareVersion,
    streamUri,
    // Measured on every add, not only when ONVIF stays silent (ADR-087).
    // ONVIF reports what the camera is *configured* for; this reports what
    // actually arrives. When they disagree -- set to 30, delivering 15 --
    // the camera is fine and the network isn't, which no other part of the
    // system would ever surface, and which needs completely different
    // advice from "change the setting". Costs ~5s on a one-time step.
    profile: profile && streamUri
      ? { ...profile, measuredFps: await measureStreamFps(authenticatedStreamUri({ streamUri, username, password })) }
      : profile,
    connectionType: "onvif",
    addedAt: new Date().toISOString(),
  };
  const cameras = listCameras();
  cameras.push(camera);
  saveCameras(cameras);
  return camera;
}

const SAMPLE_CLIP_EXT = new Set([".mp4", ".mov", ".mkv", ".avi", ".MP4", ".MOV", ".MKV", ".AVI"]);

// "Sample clip" source (2026-09-03, ManualAddDialog's dropdown): a local
// video file stands in for a live camera, so calibration and the cloud
// pipeline can be exercised without a real, court-facing camera -- neither
// camera on this network has reliably been one (see the day's progress
// notes). No `existingByHostname` dedup here -- a sample-clip camera has
// no hostname, so that check doesn't apply and isn't called.
export async function addCameraFromSampleClip({ label, filePath }) {
  if (!filePath || !existsSync(filePath)) throw new Error("File not found: " + filePath);
  const ext = path.extname(filePath);
  if (!SAMPLE_CLIP_EXT.has(ext)) throw new Error(`Unsupported video file type ${ext || "(none)"}`);

  const camera = {
    id: randomUUID(),
    label: label || path.basename(filePath, ext),
    connectionType: "sampleClip",
    addedAt: new Date().toISOString(),
  };
  // Copied into this camera's own recordings folder (capture.js's
  // RECORDINGS_ROOT/sanitizeForPath(label)/ layout) rather than referenced
  // in place -- the original file could be moved or deleted by the
  // operator afterward, and this "camera" needs its one video to keep
  // existing for as long as the camera entry does.
  const dir = path.join(RECORDINGS_ROOT, sanitizeForPath(camera.label));
  mkdirSync(dir, { recursive: true });
  const dest = path.join(dir, "sample-clip" + ext);
  copyFileSync(filePath, dest);
  camera.sampleClipPath = dest;
  // A sample clip stands in for a camera, so it has to clear the same
  // frame-rate bar -- a 15fps clip produces the same halved results, and
  // without this it skipped the guard entirely. Reading a local file costs
  // milliseconds, unlike the live-stream probe the other two paths need.
  camera.profile = await rtspProfile(dest);

  const cameras = listCameras();
  cameras.push(camera);
  saveCameras(cameras);
  return camera;
}

export function removeCamera(id) {
  const cameras = listCameras().filter((c) => c.id !== id);
  saveCameras(cameras);
  return cameras;
}

// Name only, deliberately -- connection details (hostname/port/path/
// credentials) aren't editable yet; changing those would need the same
// re-verification addCamera/addCameraViaRtsp already do before saving,
// which this doesn't attempt.
// Re-enter a camera's username and password.
//
// Until now `renameCamera` was the only edit a stored camera allowed, on
// the reasoning that changing connection details needs the same
// verification the add flow does. True -- so this does that verification
// rather than skipping the feature: the new credentials are tested against
// the real camera BEFORE anything is written, so a typo can't replace
// working credentials with broken ones.
//
// Needed because a camera whose password changed had no repair path at
// all: the card said "Sign-in needed" and the only fix was to delete the
// camera and add it again, losing its recording history (which is keyed by
// label -- see the folder-keying bug) and its calibration.
//
// Both connection types are handled, because both can refuse a login and
// they verify differently: ONVIF re-reads device information, RTSP
// re-runs the DESCRIBE probe. testConnection already branches on
// connectionType, so this just feeds it the candidate credentials.
export async function updateCameraCredentials(id, username, password) {
  const camera = listCameras().find((c) => c.id === id);
  if (!camera) throw new Error("camera not found");

  // Throws if the camera refuses them -- caller reports it, nothing saved.
  const result = await testConnection({ ...camera, username, password });

  const cameras = listCameras();
  const next = cameras.map((c) =>
    c.id === id
      ? {
          ...c,
          username,
          password,
          // An RTSP-direct camera stores credentials inside streamUri, so
          // updating the fields alone would leave the old password in the
          // URL that recording and live view actually use. Re-derive it
          // from whatever the probe confirmed.
          streamUri: result.streamUri ?? rebuildStreamUri(c, username, password),
        }
      : c,
  );
  saveCameras(next);
  return publicCamera(next.find((c) => c.id === id));
}

// Swaps the credentials inside a stored rtsp:// URL, leaving host, port,
// path and query exactly as they were -- those were confirmed working when
// the camera was added and must not be reconstructed from parts.
function rebuildStreamUri(camera, username, password) {
  if (!camera.streamUri) return camera.streamUri;
  try {
    const url = new URL(camera.streamUri);
    url.username = encodeURIComponent(username);
    url.password = encodeURIComponent(password);
    return url.toString();
  } catch {
    return camera.streamUri;
  }
}

export function renameCamera(id, label) {
  const cameras = listCameras();
  const next = cameras.map((c) => (c.id === id ? { ...c, label } : c));
  saveCameras(next);
  return next.find((c) => c.id === id);
}

// Refreshes what a camera says it's streaming. Called from the heartbeat's
// own connection check (cloud.js), which already talks to every camera --
// so this both backfills cameras added before `profile` existed and notices
// when someone changes a camera's settings from its own web page, without
// a second round of connections. Only writes when something actually
// changed, since the heartbeat runs every 30s and this store is on disk.
export function setCameraProfile(id, profile) {
  if (!profile) return null;
  const cameras = listCameras();
  const current = cameras.find((c) => c.id === id);
  if (!current) return null;
  // measuredFps is deliberately carried over rather than refreshed: it
  // costs a ~5s live probe, which is fine on a one-time add but not every
  // 30s on every camera. Without this the heartbeat's ONVIF-only profile
  // would silently wipe it and take the frame-rate guard back to trusting
  // the configured number alone.
  // Preserve the stored measurement when the caller doesn't supply one --
  // the ONVIF heartbeat profile has no measuredFps and would otherwise wipe
  // it every 30s. But a caller that DOES supply one (cloud.js's backfill)
  // must win, or the backfill silently writes nothing.
  const merged = {
    ...profile,
    measuredFps: profile.measuredFps ?? current.profile?.measuredFps ?? null,
    // Carried with the measurement they describe, so the heartbeat's
    // ONVIF-only profile can't strand a value without its timestamp.
    measuredAt: profile.measuredAt ?? current.profile?.measuredAt ?? null,
    measuredAtFps: profile.measuredAtFps ?? current.profile?.measuredAtFps ?? null,
  };
  const same = current.profile
    && ["codec", "width", "height", "fps", "bitrateKbps", "measuredFps", "measuredAt", "measuredAtFps"]
      .every((k) => (current.profile[k] ?? null) === (merged[k] ?? null));
  if (same) return current;
  const next = cameras.map((c) => (c.id === id ? { ...c, profile: merged } : c));
  saveCameras(next);
  return next.find((c) => c.id === id);
}


// --- RTSP-direct fallback (2026-09-01) ------------------------------
// For cameras where ONVIF doesn't work (disabled, misconfigured, or -- a
// real case this session -- switched to a different operation mode
// entirely) but a real video stream exists anyway. RTSP gives no device
// metadata the way ONVIF's GetDeviceInformation does (manufacturer here
// comes from vendorLookup.js's MAC lookup instead, model/serial/firmware
// stay "Not available"), but for this product's actual job -- cutting
// highlights from footage -- a working stream is what matters, and ONVIF
// was never a hard requirement for that, just the easiest way to get one
// when it's available.

// Tries the short generic path list (rtspProbe.js) with credentials the
// user already entered for an ONVIF attempt that just failed. Doesn't
// throw on "nothing worked" -- that's a normal outcome (an unusual/
// nonstandard camera), not an error; the caller decides what to offer
// next (the raw-URL fallback).
export async function probeRtspFallback({ hostname, port, username, password }) {
  return findWorkingRtspPath({ hostname, port: port || 554, username, password });
}

// Verifies one exact, fully-specified RTSP URL the user supplied
// themselves (found in the camera's own app/settings) -- the true last
// resort once neither ONVIF nor the generic path guesses worked. Accepts
// credentials embedded in the URL (rtsp://user:pass@host:port/path, what
// the camera's own app would show) or supplied separately.
export function parseRtspUrl(raw, fallbackUsername, fallbackPassword) {
  const url = new URL(raw);
  if (url.protocol !== "rtsp:") throw new Error("Must start with rtsp://");
  return {
    hostname: url.hostname,
    port: Number(url.port) || 554,
    path: url.pathname + url.search,
    username: decodeURIComponent(url.username) || fallbackUsername,
    password: decodeURIComponent(url.password) || fallbackPassword,
  };
}

export async function addCameraViaRtsp({ label, hostname, port, path, username, password }) {
  const existing = existingByHostname(hostname);
  if (existing) return existing;
  port = port || 554;
  await describeRtspStream({ hostname, port, path, username, password }); // throws if not real
  const streamUri = `rtsp://${encodeURIComponent(username)}:${encodeURIComponent(password)}@${hostname}:${port}${path}`;
  const vendors = vendorsForIps([hostname]);
  const vendor = vendors[hostname] ?? null;
  const camera = {
    id: randomUUID(),
    label: label || (vendor ? `${vendor} camera` : "Camera"),
    hostname,
    port,
    path,
    username,
    password,
    manufacturer: vendor,
    model: null,
    serialNumber: null,
    firmwareVersion: null,
    streamUri: streamUri,
    // An RTSP-added camera never went through ONVIF, so nothing else knows
    // its codec, resolution, frame rate or bitrate -- all of it comes from
    // sampling the stream (ADR-087). Without this it would show nothing and
    // skip the frame-rate guard entirely, which is how a venue ends up at
    // 15fps unnoticed. `fps` deliberately stays null: this is what the
    // camera is *sending*, not what it is *set* to, so the guard can't
    // claim the settings are fine and blame the network instead.
    profile: await rtspProfile(streamUri),
    connectionType: "rtsp",
    addedAt: new Date().toISOString(),
  };
  const cameras = listCameras();
  cameras.push(camera);
  saveCameras(cameras);
  return camera;
}
