// Measures a venue's real upstream by uploading throwaway bytes to R2
// through a presigned PUT -- the same transport, endpoint and single
// stream a recording segment takes (consoleApi.js's putStream, shared
// deliberately).
//
// Why not a speedtest library: the number that matters here isn't "what
// can this link do to a nearby server", it's "how long will a two-hour
// session take to reach R2". Those differ, sometimes by a lot, and the
// second one is the one that decides whether a venue's reels arrive
// while the players are still in the building. A venue's session upload
// is ~1.5-3 Mbps of recorded video per camera (measured, not assumed --
// see the sample recordings this was calibrated against), so an upstream
// under that per camera can never catch up at all.
//
// Deliberately synthetic bytes rather than a real recording: nothing
// private leaves the venue for a speed test, there's no 200 MB temp file
// written to a venue laptop's disk, and the test works before the first
// camera is even recorded.
import { randomBytes } from "node:crypto";
import { Readable } from "node:stream";
import { consoleFetch, putStream, requireConnection } from "./consoleApi.js";
import { logEvent } from "./activityLog.js";

// Ladder, smallest first. A slow venue answers on the first rung (8 MB
// at 2 Mbps is ~32s, already too long to make anyone sit through twice);
// a fast one blows through it in under a second, where TLS setup and TCP
// slow start would be most of what got measured, so it escalates.
export const TEST_SIZES = [8 * 1024 * 1024, 64 * 1024 * 1024, 256 * 1024 * 1024];

// Bytes sent before the connection is at speed are excluded from the
// headline number: TLS handshake, TCP slow start, and the first few MB
// the kernel accepts into the socket buffer faster than the wire drains
// it. Two seconds covers all three on any link this is meant to measure.
export const WARMUP_MS = 2000;

// A run shorter than this measured mostly warmup, so climb the ladder.
export const MIN_USEFUL_MS = 6000;

// What a camera actually produces, from the real recordings in
// ~/pic-vision-recordings: 2880x1620 h264 measured 1.57 and 2.84 Mbps on
// two different sessions. Budget the high end -- it's VBR, a bright busy
// court costs more than an empty one.
export const CAMERA_MBPS = 3;

/**
 * Throughput over the steady-state window: everything after the warmup,
 * ending when the endpoint acknowledged the last byte.
 *
 * Anchored on the *end* rather than on progress samples alone, because a
 * progress callback fires when a chunk is handed to the socket, not when
 * it lands. Counting `total - sentAtWarmup` bytes against the response
 * time makes the tail exact and confines the socket-buffer error to the
 * warmup boundary, where it belongs.
 *
 * Falls back to the whole-transfer average when the run was too short to
 * have a steady state -- which is honest rather than convenient: that
 * average is the pessimistic reading, and a run that short is escalated
 * anyway.
 */
export function steadyStateMbps(samples, totalBytes, startedAt, endedAt) {
  const overall = () => {
    const ms = endedAt - startedAt;
    return ms > 0 ? (totalBytes * 8) / ms / 1000 : 0;
  };
  const warmupEnd = startedAt + WARMUP_MS;
  const sample = samples.find((s) => s.at >= warmupEnd);
  if (!sample) return overall();
  const bytes = totalBytes - sample.sent;
  const ms = endedAt - sample.at;
  if (bytes <= 0 || ms < 500) return overall();
  return (bytes * 8) / ms / 1000;
}

// How many times the settled size is repeated. Measured 2026-09-08 from
// this workstation: consecutive 8 MB PUTs to the same bucket returned
// 28.8, 3.4, 29.0 and 32.3 Mbps -- the same client, minutes apart, on
// both IPv4 and IPv6 (an early "it's the IP family" reading was checked
// and is wrong). A path to storage that is sometimes 3 Mbps and
// sometimes 30 cannot be characterised by one sample, and reporting
// either number alone would send a venue survey the wrong way.
export const SAMPLE_COUNT = 3;

// ...but not at the cost of standing in a venue for five minutes. A
// genuinely slow link spends its whole budget on the first sample or two.
export const SAMPLE_BUDGET_MS = 60_000;

// Fastest-over-slowest above this is reported as an unstable path rather
// than folded into one confident number.
export const UNSTABLE_SPREAD = 2;

export function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Next rung of the ladder, or null when this run is long enough to trust. */
export function nextTestSize(sizeBytes, elapsedMs) {
  if (elapsedMs >= MIN_USEFUL_MS) return null;
  const index = TEST_SIZES.indexOf(sizeBytes);
  if (index === -1 || index === TEST_SIZES.length - 1) return null;
  return TEST_SIZES[index + 1];
}

/** Minutes to upload one session's recording at this measured rate. */
export function sessionUploadMinutes(mbps, hours = 2, cameras = 1) {
  if (!(mbps > 0)) return null;
  const sessionMegabits = CAMERA_MBPS * cameras * hours * 3600;
  return sessionMegabits / mbps / 60;
}

/**
 * The verdict a venue survey actually needs, in the terms of the thing
 * that will go wrong. "Below" is the case where uploads can never catch
 * up with recording, so every session falls further behind the last.
 */
export function verdict(mbps, cameras = 1) {
  const floor = CAMERA_MBPS * cameras;
  if (mbps < floor) return "below";
  if (sessionUploadMinutes(mbps, 2, cameras) > 30) return "slow";
  return "ok";
}

/**
 * `bytes` of incompressible data, without allocating `bytes` of memory or
 * touching disk: one random block, repeated. Nothing on this path
 * compresses a PUT body, so repetition costs nothing in accuracy.
 */
export function syntheticBody(bytes) {
  const block = randomBytes(256 * 1024);
  let remaining = bytes;
  return new Readable({
    read() {
      if (remaining <= 0) return this.push(null);
      const chunk = remaining >= block.length ? block : block.subarray(0, remaining);
      remaining -= chunk.length;
      this.push(chunk);
    },
  });
}

// Live state for the renderer to poll, same shape as pipeline.js's
// status: this runs for up to a minute or two and the page needs a
// progress bar, not a promise that resolves eventually.
let state = { running: false, stage: "idle", sentBytes: 0, totalBytes: 0, result: null, error: null };

export function bandwidthStatus() {
  return { ...state };
}

async function runOnce(sizeBytes, sampleIndex = 1) {
  const { key, url, bytes } = await consoleFetch("/api/agents/bandwidth-test", {
    method: "POST",
    body: { bytes: sizeBytes },
  });
  const total = bytes ?? sizeBytes;

  const samples = [];
  const startedAt = Date.now();
  state = { ...state, stage: "uploading", sentBytes: 0, totalBytes: total, sample: sampleIndex, sampleTotal: SAMPLE_COUNT };
  try {
    await putStream(url, syntheticBody(total), total, (sent) => {
      samples.push({ at: Date.now(), sent });
      state = { ...state, sentBytes: sent };
    });
  } finally {
    // Best-effort: an interrupted test leaves an object behind, which the
    // bucket's lifecycle rule on bwtest/ is the backstop for.
    consoleFetch(`/api/agents/bandwidth-test?key=${encodeURIComponent(key)}`, { method: "DELETE" }).catch(() => {});
  }
  const endedAt = Date.now();
  return {
    sizeBytes: total,
    elapsedMs: endedAt - startedAt,
    mbps: steadyStateMbps(samples, total, startedAt, endedAt),
  };
}

/**
 * Climbs the size ladder until a run is long enough to trust, then
 * repeats that size a few times and reports the median.
 *
 * Earlier, smaller rungs are discarded rather than averaged in: they
 * measured a shorter window on the same link, so they're the same
 * measurement with more noise, not extra evidence. The repeats at the
 * settled size are different -- they're what tells a venue whose uplink
 * is genuinely slow apart from one whose path to storage happens to be
 * having a bad minute, and the two need different answers.
 */
export async function runBandwidthTest({ cameras = 1 } = {}) {
  if (state.running) throw new Error("A speed test is already running");
  requireConnection();

  state = { running: true, stage: "starting", sentBytes: 0, totalBytes: 0, result: null, error: null };
  try {
    let size = TEST_SIZES[0];
    let run;
    for (;;) {
      run = await runOnce(size);
      const next = nextTestSize(size, run.elapsedMs);
      if (!next) break;
      size = next;
    }

    const samples = [run.mbps];
    let spent = run.elapsedMs;
    while (samples.length < SAMPLE_COUNT && spent < SAMPLE_BUDGET_MS) {
      const repeat = await runOnce(size, samples.length + 1);
      samples.push(repeat.mbps);
      spent += repeat.elapsedMs;
    }
    const mbps = median(samples);
    const slowest = Math.min(...samples);
    const fastest = Math.max(...samples);

    const result = {
      mbps,
      samples,
      slowest,
      fastest,
      unstable: samples.length > 1 && fastest / slowest > UNSTABLE_SPREAD,
      sizeBytes: run.sizeBytes,
      elapsedMs: spent,
      sessionMinutes: sessionUploadMinutes(mbps, 2, cameras),
      slowestSessionMinutes: sessionUploadMinutes(slowest, 2, cameras),
      verdict: verdict(mbps, cameras),
      cameras,
      at: new Date().toISOString(),
    };
    state = { running: false, stage: "done", sentBytes: run.sizeBytes, totalBytes: run.sizeBytes, result, error: null };
    logEvent(
      "benchmark_upload",
      `Upload speed measured: ${result.mbps.toFixed(1)} Mbps`,
      `${samples.length} × ${(run.sizeBytes / 1e6).toFixed(0)} MB (${samples.map((m) => m.toFixed(1)).join(", ")} Mbps) — ` +
        `a 2-hour session on ${cameras} camera${cameras === 1 ? "" : "s"} would take about ` +
        `${Math.round(result.sessionMinutes)} minutes to upload` +
        (result.unstable ? `, or ${Math.round(result.slowestSessionMinutes)} at the slowest speed measured` : ""),
    );
    return result;
  } catch (err) {
    state = { running: false, stage: "error", sentBytes: 0, totalBytes: 0, result: null, error: err.message };
    logEvent("benchmark_failed", "Upload speed test failed", err.message);
    throw err;
  }
}
