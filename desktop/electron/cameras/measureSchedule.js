// When to re-measure a camera's frame rate (operator, 2026-11-09). Pure, so
// it runs under plain `node --test` like frameRate.js.
//
// A single 5-second probe every 10 minutes was the whole policy. Right after
// a camera is added or the app starts, that first probe lands while the
// stream is still settling and can read low, and the reading then stood for
// 10 minutes -- exactly when someone is watching and about to record. So a
// camera is re-measured every minute while it settles, and a start that its
// last reading would refuse gets one fresh look first.
import { frameRateProblem } from "./frameRate.js";

export const SETTLE_MS = 10 * 60 * 1000;
export const SETTLE_TTL_MS = 60 * 1000;
export const STEADY_TTL_MS = 10 * 60 * 1000;
// Three times the old sample: a blip moves a 15-second count a third as much.
export const PROBE_SECONDS = 15;

const time = (iso) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? t : null;
};

// Settling: the camera was added, or this app started, less than SETTLE_MS ago.
export function isSettling(camera, { now, appStartedAt }) {
  const since = Math.max(appStartedAt, time(camera.addedAt) ?? 0);
  return now - since < SETTLE_MS;
}

export function needsMeasuring(camera, { now, appStartedAt }) {
  const p = camera.profile ?? {};
  if (p.measuredFps == null) return true;
  if (camera.connectionType !== "onvif"
      && (p.codec == null || p.width == null || p.height == null || p.bitrateKbps == null)) return true;
  // A changed configured rate means the camera was reconfigured, so the
  // stored measurement describes the old setting and must not outlive it.
  // This matters because effectiveFps() prefers the measured value: a
  // stale one would override the fresh configured one indefinitely.
  if (p.measuredAtFps != null && p.fps != null && p.measuredAtFps !== p.fps) return true;
  const measuredAt = time(p.measuredAt);
  if (measuredAt === null) return true;
  return now - measuredAt > (isSettling(camera, { now, appStartedAt }) ? SETTLE_TTL_MS : STEADY_TTL_MS);
}

// Only when the stored reading would refuse the start, and a new one could
// change that: a camera whose last reading passes starts at once, since
// a check here delays the recording by PROBE_SECONDS.
export function needsCheckBeforeStart(camera) {
  if (camera.connectionType === "sampleClip" || !camera.streamUri) return false;
  return frameRateProblem(camera) !== null;
}
