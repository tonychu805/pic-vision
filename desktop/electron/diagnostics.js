// The non-network-speed half of the Diagnostics tab: the checks a venue
// survey needs alongside the upload benchmark (bandwidth.js), each one
// reading something the app already computes rather than inventing a new
// signal.
//
// Everything here returns a plain, renderer-safe summary. Camera records
// hold credentials; what leaves this module is a label, a reachability
// verdict and a stream profile, never the record itself (ADR-088).
import { existsSync, statfs } from "node:fs";
import os from "node:os";
import { RECORDINGS_ROOT } from "./capture.js";
import { listCameras, testConnection } from "./cameras/store.js";
import { consoleFetch } from "./consoleApi.js";
import { getCloudConnection } from "./cloud.js";
import { CAMERA_MBPS } from "./bandwidth.js";

// 30fps is a hard requirement, not a preference: at 15fps recall halves
// (ADR-086/087). A camera can pass its connection check and still be
// useless, so the survey has to look at the measured rate, not just
// whether the stream opens.
const REQUIRED_FPS = 30;

/**
 * Round-trip to the cloud console over the agent's own authenticated
 * route -- the same call the heartbeat loop makes every 30s, so a
 * failure here is a failure there.
 */
export async function checkConsole() {
  const connection = getCloudConnection();
  if (!connection?.apiToken) {
    return { ok: false, detail: "This device isn't connected to the cloud console yet" };
  }
  const startedAt = Date.now();
  try {
    await consoleFetch("/api/agents/commands");
    return { ok: true, latencyMs: Date.now() - startedAt, consoleUrl: connection.consoleUrl };
  } catch (err) {
    return { ok: false, latencyMs: Date.now() - startedAt, consoleUrl: connection.consoleUrl, detail: err.message };
  }
}

/**
 * Reachability plus stream profile for every configured camera.
 *
 * The profile is whatever the last real connection measured (store.js
 * records codec/resolution/fps/bitrate on connect) rather than a fresh
 * 5-second ffmpeg measurement per camera -- this page already spends a
 * minute on the upload test, and a stale profile is visibly stale
 * (it names when it was measured) rather than silently wrong.
 */
export async function checkCameras() {
  const cameras = listCameras();
  const results = [];
  for (const camera of cameras) {
    const profile = camera.profile ?? {};
    const fps = profile.measuredFps ?? profile.fps ?? null;
    let reachable = true;
    let detail = null;
    try {
      await testConnection(camera);
    } catch (err) {
      reachable = false;
      detail = err.message;
    }
    results.push({
      id: camera.id,
      label: camera.label,
      reachable,
      detail,
      codec: profile.codec ?? null,
      width: profile.width ?? null,
      height: profile.height ?? null,
      fps,
      fpsOk: fps == null ? null : fps >= REQUIRED_FPS - 0.5,
      bitrateKbps: profile.bitrateKbps ?? null,
      measuredAt: profile.measuredAt ?? null,
    });
  }
  return results;
}

/** Free space where recordings land, and what that's worth in hours. */
export function checkDisk() {
  const target = existsSync(RECORDINGS_ROOT) ? RECORDINGS_ROOT : os.homedir();
  return new Promise((resolve) => {
    statfs(target, (err, stats) => {
      if (err) return resolve({ ok: false, detail: err.message, path: target });
      const freeBytes = stats.bavail * stats.bsize;
      resolve({
        ok: true,
        path: target,
        freeBytes,
        totalBytes: stats.blocks * stats.bsize,
        // One camera's worth, at the bitrate a real recording measured.
        recordingHours: freeBytes / ((CAMERA_MBPS * 1e6) / 8) / 3600,
      });
    });
  });
}

/** Everything except the upload benchmark, which the page runs separately. */
export async function runChecks() {
  const [console_, cameras, disk] = await Promise.all([checkConsole(), checkCameras(), checkDisk()]);
  return { console: console_, cameras, disk, at: new Date().toISOString() };
}
