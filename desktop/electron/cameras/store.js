// Persisted list of cameras the venue owner has added (manually, or kept
// from a discovery result), plus the connect/describe logic both the
// "add camera" and "test connection" UI actions need.
//
// POC note: camera passwords are stored in electron-store's plain JSON file
// (~/.config/<app>/cameras.json on Linux) -- fine for local dev, not for a
// client shipped to real venues. Same class of problem STRATEGY.md §5
// already flags for RunPod/R2 credentials ("cannot ship .env values to
// external venue owners") -- whatever secret-storage fix that gets should
// cover this too, not be solved separately.
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
import { RECORDINGS_ROOT, sanitizeForPath } from "../capture.js";

const store = new Store({ name: "cameras" });

export function listCameras() {
  return store.get("cameras", []);
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
  return { info, streamUri };
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
  const { info, streamUri } = await testConnection({ hostname, port, username, password, path });
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
    connectionType: "onvif",
    addedAt: new Date().toISOString(),
  };
  const cameras = listCameras();
  cameras.push(camera);
  store.set("cameras", cameras);
  return camera;
}

const SAMPLE_CLIP_EXT = new Set([".mp4", ".mov", ".mkv", ".avi", ".MP4", ".MOV", ".MKV", ".AVI"]);

// "Sample clip" source (2026-09-03, ManualAddDialog's dropdown): a local
// video file stands in for a live camera, so calibration and the cloud
// pipeline can be exercised without a real, court-facing camera -- neither
// camera on this network has reliably been one (see the day's progress
// notes). No `existingByHostname` dedup here -- a sample-clip camera has
// no hostname, so that check doesn't apply and isn't called.
export function addCameraFromSampleClip({ label, filePath }) {
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

  const cameras = listCameras();
  cameras.push(camera);
  store.set("cameras", cameras);
  return camera;
}

export function removeCamera(id) {
  const cameras = listCameras().filter((c) => c.id !== id);
  store.set("cameras", cameras);
  return cameras;
}

// Name only, deliberately -- connection details (hostname/port/path/
// credentials) aren't editable yet; changing those would need the same
// re-verification addCamera/addCameraViaRtsp already do before saving,
// which this doesn't attempt.
export function renameCamera(id, label) {
  const cameras = listCameras();
  const next = cameras.map((c) => (c.id === id ? { ...c, label } : c));
  store.set("cameras", next);
  return next.find((c) => c.id === id);
}

// Points at a per-camera calib.json (invalidated only by the camera
// physically moving -- ADR-049), so pipeline.js's cloud job has something
// to pass as --calib. Two callers: calibration.js's saveCalibration()
// after a live snapshot-and-click pass (the primary flow), or an existing
// file the operator picked via a native file dialog (system.js's
// pickCalibFile) -- e.g. one produced by
// cloud_pipeline/setup_venue_calibration.py, or another camera's already-
// clicked calibration for a reused mount. Either way this function only
// remembers the path; it never computes a calibration itself.
export function setCalibPath(id, calibPath) {
  const cameras = listCameras();
  const next = cameras.map((c) => (c.id === id ? { ...c, calibPath } : c));
  store.set("cameras", next);
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
    streamUri: `rtsp://${encodeURIComponent(username)}:${encodeURIComponent(password)}@${hostname}:${port}${path}`,
    connectionType: "rtsp",
    addedAt: new Date().toISOString(),
  };
  const cameras = listCameras();
  cameras.push(camera);
  store.set("cameras", cameras);
  return camera;
}
