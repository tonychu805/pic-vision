// measureStreamProfile itself, run end to end against a real ffprobe.
//
// This exists because of a crash that reached a shipped build (1.5.0,
// 2026-09-19): PIC-150 moved the frame-rate maths out into
// estimateFpsFromPacketTimes and deleted the `span` variable along with
// the old estimator, but the bitrate line in the enclosing function still
// referenced it. Every call threw `ReferenceError: span is not defined`
// from inside the ffprobe close handler -- where no promise catches it --
// so the packaged app died on launch with an uncaught-exception dialog.
//
// capture.test.js covers the pure estimator thoroughly, and its header
// explains that it stays pure so it needs "no real camera or a real
// ffprobe process". That reasoning is right about cameras and was wrong
// about the wrapper: nothing ever executed the function the bug was in.
// Nine passing tests said the frame-rate work was fine while the code
// path that uses it could not run at all.
//
// The project's rule is against pulling frames or streams from REAL
// HARDWARE. A file ffmpeg generates here from a synthetic pattern is not
// that -- it's the same synthetic-data principle, carried far enough to
// actually run the function.
import assert from "node:assert/strict";
import { test, before, after } from "node:test";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { FFMPEG } from "./binaries.js";
import { measureStreamProfile } from "./capture.js";

let dir;
let clip;

before(() => {
  dir = mkdtempSync(path.join(os.tmpdir(), "capture-profile-"));
  clip = path.join(dir, "synthetic-30fps.mp4");
  const result = spawnSync(
    FFMPEG,
    ["-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", clip],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 0, `could not build the test clip: ${result.stderr?.slice(-300)}`);
  assert.ok(existsSync(clip));
});

after(() => rmSync(dir, { recursive: true, force: true }));

test("a real profile measurement returns every field, bitrate included", { timeout: 30_000 }, async () => {
  const profile = await measureStreamProfile(clip, { seconds: 2 });

  // Before the fix this never arrived: the close handler threw instead of
  // resolving, so the promise simply never settled.
  assert.ok(profile, "measureStreamProfile returned nothing for a valid file");

  assert.equal(profile.codec, "H264");
  assert.equal(profile.width, 320);
  assert.equal(profile.height, 240);
  assert.ok(profile.fps > 29 && profile.fps < 31, `expected ~30fps, got ${profile.fps}`);

  // The field that carried the bug. A number, not null and not a throw --
  // this is the assertion that distinguishes the fix from the crash.
  assert.equal(typeof profile.bitrateKbps, "number", "bitrate missing from a measurable clip");
  assert.ok(profile.bitrateKbps > 0, `expected a positive bitrate, got ${profile.bitrateKbps}`);
});

test("an unreadable file is reported as unmeasurable, not as a crash", { timeout: 30_000 }, async () => {
  // The paired half: the error path has to stay a clean null. It shares
  // the same close handler, so a throw in there takes this down too.
  assert.equal(await measureStreamProfile(path.join(dir, "does-not-exist.mp4"), { seconds: 1 }), null);
});
