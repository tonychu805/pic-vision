// Dual-stream plan Stage 5. The project's rule is against pulling frames
// from REAL hardware, not against real ffmpeg on synthetic data -- same
// reasoning as capture-profile.test.js's own header. Recordings land
// under $HOME/pic-vision-recordings; a fake HOME keeps this out of the
// real one, same convention as capture-lifecycle.test.js.
import assert from "node:assert/strict";
import { test, before, after } from "node:test";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { FFMPEG, FFPROBE } from "./binaries.js";

const home = mkdtempSync(path.join(tmpdir(), "high-res-fetch-"));
process.env.HOME = home;
const { RECORDINGS_ROOT } = await import("./capture.js");
const { findRecordingForPart, partElapsedRange, mainSegmentsForRange, trimHighRes } = await import("./highResFetch.js");

after(() => rmSync(home, { recursive: true, force: true }));

// ---------- findRecordingForPart ----------

test("finds the main recording whose sub-stream sibling has the named part", () => {
  const camId = "find-part-cam";
  const mainDir = path.join(RECORDINGS_ROOT, camId, "2026-10-09T00-00-00-000Z");
  const partDir = path.join(`${mainDir}-sub`, "parts", "part-01");
  mkdirSync(mainDir, { recursive: true });
  mkdirSync(partDir, { recursive: true });
  writeFileSync(path.join(partDir, "session-003.mkv"), "");

  const located = findRecordingForPart({ id: camId }, 1);
  assert.equal(located.mainDir, mainDir);
  assert.equal(located.part.name, "part-01");
  assert.deepEqual(located.part.segments, ["session-003.mkv"]);
});

test("a part index this camera never had returns null, not a wrong match", () => {
  const camId = "find-part-missing";
  const mainDir = path.join(RECORDINGS_ROOT, camId, "2026-10-09T01-00-00-000Z");
  mkdirSync(path.join(`${mainDir}-sub`, "parts", "part-01"), { recursive: true });
  assert.equal(findRecordingForPart({ id: camId }, 99), null);
});

test("a camera with no recordings at all returns null", () => {
  assert.equal(findRecordingForPart({ id: "find-part-no-recordings" }, 1), null);
});

// ---------- partElapsedRange ----------

test("a part's elapsed range spans its first segment's start to its last segment's end", () => {
  const range = partElapsedRange({ segments: ["session-003.mkv", "session-004.mkv"] });
  assert.deepEqual(range, { startSec: 1800, endSec: 3000 }); // 3*600 .. (4+1)*600
});

test("partElapsedRange doesn't care what order the segments arrive in", () => {
  const sorted = partElapsedRange({ segments: ["session-003.mkv", "session-004.mkv"] });
  const reversed = partElapsedRange({ segments: ["session-004.mkv", "session-003.mkv"] });
  assert.deepEqual(sorted, reversed);
});

// ---------- mainSegmentsForRange ----------

test("selects exactly main's own segments whose index falls in the part's elapsed range", () => {
  const mainDir = mkdtempSync(path.join(tmpdir(), "main-segments-"));
  for (const n of [0, 1, 2, 3, 4, 5, 6]) writeFileSync(path.join(mainDir, `session-${String(n).padStart(3, "0")}.mkv`), "");
  const found = mainSegmentsForRange(mainDir, 1800, 3000); // indices 3..4
  assert.deepEqual(found, ["session-003.mkv", "session-004.mkv"]);
  rmSync(mainDir, { recursive: true, force: true });
});

test("a main recording that doesn't exist (already cleaned up) returns no segments, not a throw", () => {
  assert.deepEqual(mainSegmentsForRange(path.join(home, "never-existed"), 0, 600), []);
});

// ---------- trimHighRes: real ffmpeg, synthetic data ----------

let segA, segB, outDir;

before(() => {
  outDir = mkdtempSync(path.join(tmpdir(), "trim-high-res-"));
  segA = path.join(outDir, "session-000.mkv");
  segB = path.join(outDir, "session-001.mkv");
  for (const [seg, color] of [[segA, "red"], [segB, "blue"]]) {
    const result = spawnSync(FFMPEG, [
      "-y", "-f", "lavfi", "-i", `color=c=${color}:size=320x240:rate=30:duration=5`,
      "-c:v", "libx264", "-pix_fmt", "yuv420p", seg,
    ], { encoding: "utf8" });
    assert.equal(result.status, 0, `could not build test segment: ${result.stderr?.slice(-300)}`);
  }
});

after(() => rmSync(outDir, { recursive: true, force: true }));

function probedDuration(file) {
  const result = spawnSync(FFPROBE, [
    "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file,
  ], { encoding: "utf8" });
  return parseFloat(result.stdout);
}

test("trims a cut spanning two concatenated segments to exactly the requested window", { timeout: 30_000 }, async () => {
  const out = path.join(outDir, "clip.mp4");
  // Two 5s segments concatenated = 10s; cut [3, 7] spans the join at 5s.
  await trimHighRes([segA, segB], 3, 7, out);
  assert.ok(existsSync(out));
  const dur = probedDuration(out);
  assert.ok(Math.abs(dur - 4) < 0.3, `expected ~4s, got ${dur}`);
});

test("a cut entirely inside the first segment never reaches the second", { timeout: 30_000 }, async () => {
  const out = path.join(outDir, "clip-first-only.mp4");
  await trimHighRes([segA, segB], 1, 3, out);
  const dur = probedDuration(out);
  assert.ok(Math.abs(dur - 2) < 0.3, `expected ~2s, got ${dur}`);
});
