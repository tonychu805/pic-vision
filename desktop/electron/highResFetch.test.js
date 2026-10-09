// Dual-stream plan Stage 5. The project's rule is against pulling frames
// from REAL hardware, not against real ffmpeg on synthetic data -- same
// reasoning as capture-profile.test.js's own header. Recordings land
// under $HOME/pic-vision-recordings; a fake HOME keeps this out of the
// real one, same convention as capture-lifecycle.test.js.
import assert from "node:assert/strict";
import { test, before, after } from "node:test";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, utimesSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { FFMPEG, FFPROBE } from "./binaries.js";

const home = mkdtempSync(path.join(tmpdir(), "high-res-fetch-"));
process.env.HOME = home;
const { RECORDINGS_ROOT } = await import("./capture.js");
const { findRecordingForPart, partWindow, mainWindowsOverlapping, leadSecFor, trimHighRes } = await import("./highResFetch.js");

// startRecording's own folder-naming convention -- recordingStartedAt
// parses exactly this shape back into the instant it names.
const isoDirName = (date) => date.toISOString().replace(/[:.]/g, "-");

// A segment file whose mtime is `endOffsetSec` after `recordingStart` --
// segmentWindows reads this as that segment's own end (and the next
// segment's start), same as a real ffmpeg -f segment write would leave it.
function writeSegment(dir, name, recordingStart, endOffsetSec) {
  mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  writeFileSync(file, "");
  const end = new Date(recordingStart.getTime() + endOffsetSec * 1000);
  utimesSync(file, end, end);
}

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

// ---------- partWindow / mainWindowsOverlapping: real mtimes, no drift ----------

test("a part's window spans its first segment's start to its last segment's end", () => {
  const start = new Date("2026-10-09T00:00:00.000Z");
  const subDir = mkdtempSync(path.join(tmpdir(), isoDirName(start) + "-sub-"));
  for (const n of [0, 1, 2, 3, 4]) writeSegment(subDir, `session-${String(n).padStart(3, "0")}.mkv`, start, (n + 1) * 600);

  const window = partWindow(subDir, { segments: ["session-003.mkv", "session-004.mkv"] });
  assert.equal(window.start.getTime(), start.getTime() + 1800_000); // segment 2's end
  assert.equal(window.end.getTime(), start.getTime() + 3000_000); // segment 4's end
  rmSync(subDir, { recursive: true, force: true });
});

test("selects exactly main's own segments whose real window overlaps the part's", () => {
  const start = new Date("2026-10-09T00:00:00.000Z");
  const mainDir = mkdtempSync(path.join(tmpdir(), isoDirName(start) + "-"));
  for (const n of [0, 1, 2, 3, 4, 5, 6]) writeSegment(mainDir, `session-${String(n).padStart(3, "0")}.mkv`, start, (n + 1) * 600);

  const window = { start: new Date(start.getTime() + 1800_000), end: new Date(start.getTime() + 3000_000) };
  const found = mainWindowsOverlapping(mainDir, window).map((w) => w.name);
  assert.deepEqual(found, ["session-003.mkv", "session-004.mkv"]);
  rmSync(mainDir, { recursive: true, force: true });
});

test("a main recording that doesn't exist (already cleaned up) returns no windows, not a throw", () => {
  const window = { start: new Date(0), end: new Date(600_000) };
  assert.deepEqual(mainWindowsOverlapping(path.join(home, "never-existed"), window), []);
});

// ---------- the actual fix: main/sub drift from an independent reconnect ----------

// Real mechanism this guards against: sub drops for 45s partway through
// its segment 1 and reconnects, so every one of ITS segments from then on
// runs 45s later in wall-clock terms than the equivalent main segment --
// main never dropped, so main's segments stay on the clean 600s schedule.
// The index-based approach this replaced would have picked main's segment
// 3 for sub's part at segment 3 and been wrong by 45s; this must still
// pick the main segment(s) that actually cover the same real moment.
test("a stream that reconnected and drifted still finds the right main segments, by real time not by index", () => {
  const start = new Date("2026-10-09T00:00:00.000Z");
  const DRIFT_SEC = 45;

  const mainDir = mkdtempSync(path.join(tmpdir(), isoDirName(start) + "-"));
  for (const n of [0, 1, 2, 3, 4]) writeSegment(mainDir, `session-${String(n).padStart(3, "0")}.mkv`, start, (n + 1) * 600);

  const subDir = mkdtempSync(path.join(tmpdir(), isoDirName(start) + "-sub-"));
  writeSegment(subDir, "session-000.mkv", start, 600); // segment 0: clean, before the drop
  // segment 1 onward: 45s later than the clean schedule would put them.
  for (const n of [1, 2, 3]) writeSegment(subDir, `session-${String(n).padStart(3, "0")}.mkv`, start, (n + 1) * 600 + DRIFT_SEC);

  // Sub's part 1 is segment 2 alone: real window [1245s, 1845s) wall-clock
  // (600+45 .. 1800+45), NOT [1200s, 1800s) -- what index math would assume.
  const window = partWindow(subDir, { segments: ["session-002.mkv"] });
  assert.equal(window.start.getTime(), start.getTime() + (1200 + DRIFT_SEC) * 1000);
  assert.equal(window.end.getTime(), start.getTime() + (1800 + DRIFT_SEC) * 1000);

  // That window [1245, 1845) falls entirely inside main's clean segment 2
  // ([1200, 1800)) and segment 3 ([1800, 2400)) at the boundary -- real
  // overlap, not "segment 2 because the part is named segment 2".
  const mainWindows = mainWindowsOverlapping(mainDir, window);
  assert.deepEqual(mainWindows.map((w) => w.name), ["session-002.mkv", "session-003.mkv"]);

  // leadSecFor: main's segment 2 starts 45s before the part's real window
  // -- exactly the drift that accrued.
  assert.equal(leadSecFor(mainWindows, window), DRIFT_SEC);

  rmSync(mainDir, { recursive: true, force: true });
  rmSync(subDir, { recursive: true, force: true });
});

// ---------- leadSecFor: when main can't produce a correct cut ----------

test("leadSecFor is null with no overlapping main segments, not a thrown or wrong number", () => {
  assert.equal(leadSecFor([], { start: new Date(0), end: new Date(600_000) }), null);
});

// Found in code review: a NEGATIVE gap (main's earliest overlapping
// segment starts AFTER the part's window does -- main dropped out right
// as the rally began, or hadn't started recording yet) used to be clamped
// to 0 and silently fed into the cut, shifting it by the missing amount.
// Treated the same as no overlap at all: null, not a guess.
test("leadSecFor is null, not clamped to 0, when main starts after the part's window begins", () => {
  const window = { start: new Date(1200_000), end: new Date(1800_000) };
  const mainWindows = [{ name: "session-003.mkv", start: new Date(1800_000), end: new Date(2400_000) }];
  assert.equal(leadSecFor(mainWindows, window), null);
});

test("leadSecFor is a real positive number when main's segment starts exactly on the window", () => {
  const window = { start: new Date(1200_000), end: new Date(1800_000) };
  const mainWindows = [{ name: "session-002.mkv", start: new Date(1200_000), end: new Date(1800_000) }];
  assert.equal(leadSecFor(mainWindows, window), 0);
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
