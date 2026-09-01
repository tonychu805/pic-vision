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
import { findWorkingRtspPath, describeRtspStream } from "./rtspProbe.js";
import { vendorsForIps } from "./vendorLookup.js";

const store = new Store({ name: "cameras" });

export function listCameras() {
  return store.get("cameras", []);
}

export async function testConnection({ hostname, port, username, password, path, connectionType }) {
  // Stored cameras carry their own connectionType ('onvif' or 'rtsp',
  // added by addCamera/addCameraViaRtsp) -- an RTSP-direct camera has no
  // ONVIF service to test against at all, so the periodic status check
  // (CamerasPage.jsx) needs to actually probe the way it was added, not
  // always assume ONVIF. Absent (the ONVIF add flow's own internal
  // pre-save check, before anything is stored) defaults to ONVIF, same as
  // before this branch existed.
  if (connectionType === "rtsp") {
    await describeRtspStream({ hostname, port: port || 554, path, username, password });
    return { info: {}, streamUri: null };
  }

  // path defaults to the library's own '/onvif/device_service' when
  // omitted -- but that's not universal. A real Synology camera on this
  // network (2026-09-01) serves ONVIF at '/Onvif/device_service' (capital
  // O) instead, confirmed via a raw HTTP probe (401 + WWW-Authenticate:
  // Digest realm="IPCam" there, plain 404 at the lowercase path) -- WS-
  // Discovery never found it either, so manual add is the only way in,
  // and it needs this override to actually reach the right endpoint.
  const cam = new Cam({ hostname, port: port || 80, username, password, path: path || undefined });
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

export async function addCamera({ label, hostname, port, username, password, path }) {
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

export function removeCamera(id) {
  const cameras = listCameras().filter((c) => c.id !== id);
  store.set("cameras", cameras);
  return cameras;
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
