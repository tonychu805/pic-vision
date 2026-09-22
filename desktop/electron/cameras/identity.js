// "Is this add the same camera as one already configured?" -- the rule
// addCamera / addCameraViaRtsp use to stay idempotent.
//
// Hostname alone was the rule (2026-09-01: one Synology camera added twice
// a few seconds apart). It was too coarse for RTSP: an NVR, or a camera
// with several streams, serves every channel from one host and port and
// differs only in the path, so adding a second stream silently returned the
// first one and nothing new appeared.
//
// ONVIF still keys on hostname: its port/path describe the control service,
// not a particular stream, so the same host is the same device.
// RTSP keys on host + port + path, because the path *is* the stream.
// An ONVIF entry and an RTSP entry are never treated as the same camera.

function protocolOf(camera) {
  return camera.connectionType === "rtsp" ? "rtsp" : "onvif";
}

function lower(hostname) {
  return typeof hostname === "string" ? hostname.toLowerCase() : hostname;
}

export function isSameCameraSource(existing, candidate) {
  if (!existing.hostname || !candidate.hostname) return false; // sample clips
  if (lower(existing.hostname) !== lower(candidate.hostname)) return false;
  if (protocolOf(existing) !== protocolOf(candidate)) return false;
  if (protocolOf(candidate) === "onvif") return true;
  return (
    (existing.port || 554) === (candidate.port || 554) &&
    (existing.path || "/") === (candidate.path || "/")
  );
}
