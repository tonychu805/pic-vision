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
process.env.USERPROFILE = process.env.HOME; // os.homedir() on Windows
const { RECORDINGS_ROOT } = await import("./capture.js");
const { partSessionId } = await import("./autoSplit.js");
const { findRecordingForPart, partWindow, mainWindowsOverlapping, leadSecFor, trimHighRes, viewBoxCrop } = await import("./highResFetch.js");

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

test("two recordings with the same part number: the session id picks the right one", () => {
  // The 2026-10-29 bug: the first folder with a part-03 won, so a later
  // session's clips were cut from an earlier session's recording.
  const camId = "find-part-two-sessions";
  const older = path.join(RECORDINGS_ROOT, camId, "2026-10-28T10-00-27-432Z");
  const newer = path.join(RECORDINGS_ROOT, camId, "2026-10-29T10-35-39-462Z");
  for (const dir of [older, newer]) {
    mkdirSync(dir, { recursive: true });
    mkdirSync(path.join(`${dir}-sub`, "parts", "part-03"), { recursive: true });
    writeFileSync(path.join(`${dir}-sub`, "parts", "part-03", "session-010.mkv"), "");
  }
  assert.equal(findRecordingForPart({ id: camId }, 3, "Camera-2026-10-29T10-35-39-462Z-sub-part-03").mainDir, newer);
  assert.equal(findRecordingForPart({ id: camId }, 3, "Camera-2026-10-28T10-00-27-432Z-sub-part-03").mainDir, older);
  // A session whose recording is gone from this machine: nothing, never the other one.
  assert.equal(findRecordingForPart({ id: camId }, 3, "Camera-2026-10-27T09-00-00-000Z-sub-part-03"), null);
  // No session id (an older console) and two candidates: skipped, not guessed.
  assert.equal(findRecordingForPart({ id: camId }, 3), null);
});

test("a camera label containing the folder-like text cannot match the wrong folder", () => {
  const camId = "find-part-label";
  const dir = path.join(RECORDINGS_ROOT, camId, "2026-10-29T05-21-05-452Z");
  mkdirSync(dir, { recursive: true });
  mkdirSync(path.join(`${dir}-sub`, "parts", "part-01"), { recursive: true });
  writeFileSync(path.join(`${dir}-sub`, "parts", "part-01", "session-000.mkv"), "");
  assert.equal(findRecordingForPart({ id: camId }, 1, "Court_2-2026-10-29T05-21-05-452Z-sub-part-01").mainDir, dir);
  assert.equal(findRecordingForPart({ id: camId }, 1, "Court_2-2026-10-29T05-21-05-452Z-sub-part-011"), null);
});

test("a dual-stream part is found by the session id its sub-stream upload was given", () => {
  // 2026-11-20: session ids name the folder the parts were uploaded from,
  // "<recording>-sub", and none of them matched, so no sharp or 9:16 clip was cut.
  const camId = "find-part-dual-stream";
  const dir = path.join(RECORDINGS_ROOT, camId, "2026-11-20T08-33-30-916Z");
  const subPart = path.join(`${dir}-sub`, "parts", "part-04");
  mkdirSync(dir, { recursive: true });
  mkdirSync(subPart, { recursive: true });
  writeFileSync(path.join(subPart, "session-003.mkv"), "");
  const sessionId = partSessionId("Camera", `${dir}-sub`, "part-04");
  assert.equal(sessionId, "Camera-2026-11-20T08-33-30-916Z-sub-part-04");
  const found = findRecordingForPart({ id: camId }, 4, sessionId);
  assert.equal(found.mainDir, dir);
  assert.deepEqual(found.part.segments, ["session-003.mkv"]);
});

test("a single-stream part is still found by its session id", () => {
  const camId = "find-part-single-stream";
  const dir = path.join(RECORDINGS_ROOT, camId, "2026-11-20T09-00-00-000Z");
  const part = path.join(dir, "parts", "part-02");
  mkdirSync(part, { recursive: true });
  writeFileSync(path.join(part, "session-001.mkv"), "");
  const sessionId = partSessionId("Camera", dir, "part-02");
  assert.equal(findRecordingForPart({ id: camId }, 2, sessionId).mainDir, dir);
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

test("trimHighRes converts camera PCM audio to browser-compatible AAC", { timeout: 30_000 }, async () => {
  const source = path.join(outDir, "session-with-audio.mkv");
  const made = spawnSync(FFMPEG, [
    "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=320x240:rate=30:duration=4",
    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=4",
    "-c:v", "libx264", "-c:a", "pcm_alaw", source,
  ], { encoding: "utf8" });
  assert.equal(made.status, 0, made.stderr?.slice(-300));
  const out = path.join(outDir, "clip-with-audio.mp4");
  await trimHighRes([source], 1, 3, out);
  const probed = spawnSync(FFPROBE, ["-v", "error", "-show_entries", "stream=codec_type,codec_name,sample_rate", "-of", "json", out], { encoding: "utf8" });
  assert.equal(probed.status, 0, probed.stderr);
  const streams = JSON.parse(probed.stdout).streams;
  assert.ok(streams.some((s) => s.codec_type === "video" && s.codec_name === "h264"));
  assert.ok(streams.some((s) => s.codec_type === "audio" && s.codec_name === "aac" && s.sample_rate === "48000"));
});

// ---------- view box (step 4): the sharp copy shows what the boxed reel shows ----------

// PGC Court A's box (2026-11-21): x 200-2704, y 159-1568 of a 2880x1620 calibration, as the console sends it.
const COURT_A_BOX = { left: 200 / 2880, top: 159 / 1620, right: 2704 / 2880, bottom: 1568 / 1620 }

test("a view box becomes an even, in-frame crop at the main stream's own size", () => {
  assert.deepEqual(viewBoxCrop(COURT_A_BOX, { w: 2880, h: 1620 }), { w: 2504, h: 1410, x: 200, y: 158 });
  assert.deepEqual(viewBoxCrop(COURT_A_BOX, { w: 1920, h: 1080 }), { w: 1670, h: 938, x: 132, y: 106 });
  const edge = viewBoxCrop({ left: 0.5, top: 0.5, right: 1, bottom: 1 }, { w: 1281, h: 721 });
  assert.ok(edge.x + edge.w <= 1281 && edge.y + edge.h <= 721);
  assert.ok([edge.w, edge.h, edge.x, edge.y].every((v) => v % 2 === 0));
  assert.throws(() => viewBoxCrop({ left: 0.6, top: 0, right: 0.6, bottom: 1 }, { w: 1920, h: 1080 }));
});

test("a boxed sharp copy is cut to the box from the main stream; without a box it stays whole-frame", { timeout: 60_000 }, async () => {
  const main = path.join(outDir, "main-1080.mkv");
  const made = spawnSync(FFMPEG, ["-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", main],
    { encoding: "utf8" });
  assert.equal(made.status, 0, made.stderr?.slice(-300));
  const size = (file) => spawnSync(FFPROBE, ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", file],
    { encoding: "utf8" }).stdout.trim();
  const boxed = path.join(outDir, "boxed.mp4");
  await trimHighRes([main], 1, 3, boxed, COURT_A_BOX);
  assert.equal(size(boxed), "1670,938");
  const whole = path.join(outDir, "whole.mp4");
  await trimHighRes([main], 1, 3, whole);
  assert.equal(size(whole), "1920,1080");
});
