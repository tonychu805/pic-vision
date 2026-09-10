// Two things paired here (CLAUDE.md, "a test proving X must sit beside one
// proving the feature still works"):
//
//   1. `encoderIsListed` must say no to a name ffmpeg doesn't have, not just
//      yes to one it does -- the whole point of benchmarking on top of this
//      check is that "listed" isn't "works", so the listing check itself
//      has to be exact, not a loose substring match that would claim
//      "h264_nvenc" is present because "libx264" is in the same file.
//   2. `benchmarkEncoder`/`diagnoseEncodeCapability` are run for real against
//      this machine's actual bundled ffmpeg, same as bandwidth.js's
//      synthetic-body tests run a real HTTP transfer -- a mocked spawn would
//      only prove the mock, not that a real encode measures something
//      plausible.
//
// The fixture text below is this workstation's real `ffmpeg -encoders`
// output (captured 2026-09-10), not invented -- same reasoning as
// ssdp.test.js's real device-description fixtures.
//
// What this can't cover on this box: a working hardware encoder
// (h264_videotoolbox/qsv/nvenc/amf all need hardware this Linux workstation
// doesn't have). Only the "no hardware, honest libx264 fallback" path is
// verified for real; the hardware branch is unverified until this runs on a
// Mac or an Intel/NVIDIA/AMD box.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MIN_USABLE_MULTIPLIER,
  benchmarkEncoder,
  diagnoseEncodeCapability,
  encoderIsListed,
} from "./encoderCapability.js";

const REAL_ENCODERS_TEXT = `Encoders:
 V..... = Video
 A..... = Audio
 S..... = Subtitle
 .F.... = Frame-level multithreading
 ..S... = Slice-level multithreading
 ...X.. = Codec is experimental
 ....B. = Supports draw_horiz_band
 .....D = Supports direct rendering method 1
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libx264rgb           libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 RGB (codec h264)
 V..... h264_v4l2m2m         V4L2 mem2mem H.264 encoder wrapper (codec h264)
`;

test("a name that's actually in the listing is found", () => {
  assert.equal(encoderIsListed("libx264", REAL_ENCODERS_TEXT), true);
  assert.equal(encoderIsListed("h264_v4l2m2m", REAL_ENCODERS_TEXT), true);
});

test("a name that's NOT in the listing reads as absent, not a fuzzy match", () => {
  // The failure mode this guards: "libx264" is a substring of nothing else
  // here, but "h264_nvenc" not appearing must not be papered over by a loose
  // check that matches on "h264" alone.
  assert.equal(encoderIsListed("h264_nvenc", REAL_ENCODERS_TEXT), false);
  assert.equal(encoderIsListed("h264_qsv", REAL_ENCODERS_TEXT), false);
  assert.equal(encoderIsListed("h264_videotoolbox", REAL_ENCODERS_TEXT), false);
});

test("empty or garbage listing text finds nothing", () => {
  assert.equal(encoderIsListed("libx264", ""), false);
  assert.equal(encoderIsListed("libx264", "ffmpeg version 6.0"), false);
});

test("benchmarking a real, present encoder returns a plausible realtime multiplier", async () => {
  const multiplier = await benchmarkEncoder("libx264", { seconds: 2 });
  assert.notEqual(multiplier, null, "libx264 ships in every ffmpeg-static build -- this must run");
  assert.ok(multiplier > 0, `expected a positive multiplier, got ${multiplier}`);
  // libx264 at a 2 Mbps target on any machine capable of running this test
  // suite comfortably clears realtime -- a near-zero result here would mean
  // the benchmark is measuring something other than the encode (e.g. process
  // startup dominating a too-short run).
  assert.ok(multiplier > 0.5, `suspiciously slow for libx264: ${multiplier}x`);
});

test("benchmarking a name ffmpeg doesn't have returns null, not a false success", async () => {
  const multiplier = await benchmarkEncoder("h264_nvenc", { seconds: 2, timeoutMs: 5000 });
  assert.equal(multiplier, null, "an encoder this binary doesn't support must fail loudly, not report 0 or NaN as a rate");
});

test("the full pipeline finds a usable answer on this machine for real", async () => {
  const result = await diagnoseEncodeCapability();
  assert.notEqual(result, null, "libx264 is the guaranteed floor -- there is always an answer");
  assert.equal(typeof result.encoder, "string");
  assert.ok(result.realtimeMultiplier > 0);
  assert.equal(typeof result.hardware, "boolean");

  // This workstation's ffmpeg-static bundle has no hardware H.264 encoder
  // (confirmed via the real `ffmpeg -encoders` listing above), so the
  // honest answer here is the libx264 floor, not a hardware encoder it
  // doesn't actually have.
  assert.equal(result.encoder, "libx264");
  assert.equal(result.hardware, false);
});

test("MIN_USABLE_MULTIPLIER stays above 1x realtime", () => {
  // Below 1x an encoder falls behind a single camera; the margin exists so
  // a second camera or a transient slowdown doesn't immediately break it.
  assert.ok(MIN_USABLE_MULTIPLIER > 1);
});
