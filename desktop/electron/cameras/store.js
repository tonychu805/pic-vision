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

const store = new Store({ name: "cameras" });

export function listCameras() {
  return store.get("cameras", []);
}

export async function testConnection({ hostname, port, username, password, path }) {
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
