// The venue computer's recording cleanup (recordingRetention.js).
import assert from "node:assert/strict";
import { test, after } from "node:test";
import { mkdirSync, mkdtempSync, writeFileSync, existsSync, rmSync, linkSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Recordings live under $HOME/pic-vision-recordings, read once at load.
const home = mkdtempSync(path.join(tmpdir(), "retention-"));
process.env.HOME = home;
const { retentionDecision, retentionSweep, reelDoneAt, recordingStartedAt } = await import("./recordingRetention.js");
after(() => rmSync(home, { recursive: true, force: true }));

const DAY = 86_400_000;
const NOW = Date.parse("2026-09-29T12:00:00.000Z");
const ago = (days) => NOW - days * DAY;

test("a reel finished over 7 days ago: the recording goes", () => {
  assert.equal(retentionDecision({ startedAt: ago(9), doneAt: ago(8), busy: false }, NOW).action, "delete");
});

// Paired: 7 days is counted from the reel, not from the recording.
test("a reel finished under 7 days ago keeps it, however old the recording is", () => {
  assert.equal(retentionDecision({ startedAt: ago(25), doneAt: ago(6), busy: false }, NOW).action, "keep");
});

test("no reel: kept up to 30 days, warned once the day before, then removed", () => {
  assert.equal(retentionDecision({ startedAt: ago(10), doneAt: null, busy: false }, NOW).action, "keep");
  assert.equal(retentionDecision({ startedAt: ago(29.5), doneAt: null, busy: false, warned: false }, NOW).action, "warn");
  assert.equal(retentionDecision({ startedAt: ago(29.5), doneAt: null, busy: false, warned: true }, NOW).action, "keep");
  assert.equal(retentionDecision({ startedAt: ago(31), doneAt: null, busy: false }, NOW).action, "delete");
});

// Paired with every delete above: nothing in use is ever removed.
test("a recording in progress, or uploading, is never removed", () => {
  assert.equal(retentionDecision({ startedAt: ago(60), doneAt: ago(50), busy: true }, NOW).action, "keep");
  assert.equal(retentionDecision({ startedAt: ago(60), doneAt: null, busy: true }, NOW).action, "keep");
});

test("only capture.js's timestamp folder names count as recordings", () => {
  assert.equal(recordingStartedAt("2026-09-20T09-00-00-000Z"), Date.parse("2026-09-20T09:00:00.000Z"));
  assert.equal(recordingStartedAt("notes"), null);
  assert.equal(recordingStartedAt("parts"), null);
});

// ---- against a real folder --------------------------------------------
const root = path.join(home, "pic-vision-recordings");
const folderName = (ms) => new Date(ms).toISOString().replace(/[:.]/g, "-");
function recording(camera, startedDaysAgo, { doneDaysAgo = null, parts = null } = {}) {
  const dir = path.join(root, camera, folderName(ago(startedDaysAgo)));
  mkdirSync(dir, { recursive: true });
  for (let i = 0; i < 3; i++) writeFileSync(path.join(dir, `session-00${i}.mkv`), "x");
  if (doneDaysAgo !== null && !parts) {
    mkdirSync(path.join(dir, "cloud_job"));
    writeFileSync(path.join(dir, "cloud_job", "status.json"), JSON.stringify({ stage: "done", done: true, doneAt: new Date(ago(doneDaysAgo)).toISOString() }));
  }
  if (parts) {
    parts.forEach(({ segments, doneDaysAgo: d }, n) => {
      const partDir = path.join(dir, "parts", `part-0${n + 1}`);
      mkdirSync(path.join(partDir, "cloud_job"), { recursive: true });
      for (const s of segments) linkSync(path.join(dir, s), path.join(partDir, s));
      writeFileSync(path.join(partDir, "cloud_job", "status.json"), JSON.stringify(d === null ? { stage: "error", done: false } : { stage: "done", done: true, doneAt: new Date(ago(d)).toISOString() }));
    });
  }
  return dir;
}

// ---- dual-stream: cloud_job/parts live under the sub-stream sibling, not main (Stage 2) ----
function dualStreamRecording(camera, startedDaysAgo, { doneDaysAgo = null, parts = null } = {}) {
  const dir = path.join(root, camera, folderName(ago(startedDaysAgo)));
  const subDir = `${dir}-sub`;
  mkdirSync(dir, { recursive: true });
  mkdirSync(subDir, { recursive: true });
  for (let i = 0; i < 3; i++) {
    writeFileSync(path.join(dir, `session-00${i}.mkv`), "x");
    writeFileSync(path.join(subDir, `session-00${i}.mkv`), "x");
  }
  if (doneDaysAgo !== null && !parts) {
    mkdirSync(path.join(subDir, "cloud_job"));
    writeFileSync(path.join(subDir, "cloud_job", "status.json"), JSON.stringify({ stage: "done", done: true, doneAt: new Date(ago(doneDaysAgo)).toISOString() }));
  }
  if (parts) {
    parts.forEach(({ segments, doneDaysAgo: d }, n) => {
      const partDir = path.join(subDir, "parts", `part-0${n + 1}`);
      mkdirSync(path.join(partDir, "cloud_job"), { recursive: true });
      for (const s of segments) linkSync(path.join(subDir, s), path.join(partDir, s));
      writeFileSync(path.join(partDir, "cloud_job", "status.json"), JSON.stringify(d === null ? { stage: "error", done: false } : { stage: "done", done: true, doneAt: new Date(ago(d)).toISOString() }));
    });
  }
  return { dir, subDir };
}

// The bug this guards against: reelDoneAt(dir) used to read cloud_job/
// and parts/ from `dir` itself. For a dual-stream camera those live under
// `${dir}-sub` (the Stage 2 upload-direction fix routes every real upload
// there), so main never has them -- every dual-stream recording read as
// "no reel ever made", forever, however many reels it actually produced.
test("reelDoneAt reads a dual-stream camera's completion from its sub-stream sibling, not main", () => {
  const { dir } = dualStreamRecording("cam-dual-whole", 12, { doneDaysAgo: 8 });
  assert.equal(reelDoneAt(dir), ago(8));
});

test("reelDoneAt also finds a dual-stream camera's per-part completion under the sub sibling", () => {
  const { dir } = dualStreamRecording("cam-dual-parts", 20, {
    parts: [{ segments: ["session-000.mkv", "session-001.mkv"], doneDaysAgo: 10 }, { segments: ["session-002.mkv"], doneDaysAgo: 9 }],
  });
  assert.equal(reelDoneAt(dir), ago(9));
});

test("a sweep removes a dual-stream recording's sub-stream sibling together with main, not main alone", () => {
  const { dir, subDir } = dualStreamRecording("cam-dual-old", 12, { doneDaysAgo: 8 });
  retentionSweep(NOW);
  assert.equal(existsSync(dir), false, "main should be removed");
  assert.equal(existsSync(subDir), false, "its sub-stream sibling should go with it, not be left behind");
});

// Paired: a dual-stream recording still waiting on its reel (or too young
// to be due) keeps BOTH folders -- the sub sibling is never independently
// evaluated on its own schedule, since RECORDING_DIR_RE never matches it.
test("a dual-stream recording not yet due keeps both folders, not just main", () => {
  const { dir, subDir } = dualStreamRecording("cam-dual-young", 5);
  retentionSweep(NOW);
  assert.equal(existsSync(dir), true);
  assert.equal(existsSync(subDir), true);
});

test("a sweep removes exactly the recordings the rules say, and nothing else", () => {
  const oldReel = recording("cam-1", 12, { doneDaysAgo: 8 });
  const recentReel = recording("cam-1", 11, { doneDaysAgo: 2 });
  const neverSent = recording("cam-2", 40);
  const young = recording("cam-2", 5);
  const allPartsDone = recording("cam-3", 20, { parts: [{ segments: ["session-000.mkv", "session-001.mkv"], doneDaysAgo: 10 }, { segments: ["session-002.mkv"], doneDaysAgo: 9 }] });
  const partMissing = recording("cam-3", 21, { parts: [{ segments: ["session-000.mkv", "session-001.mkv"], doneDaysAgo: 10 }] });
  const partFailed = recording("cam-4", 20, { parts: [{ segments: ["session-000.mkv", "session-001.mkv", "session-002.mkv"], doneDaysAgo: null }] });
  const notARecording = path.join(root, "cam-1", "notes");
  mkdirSync(notARecording);
  const outside = path.join(home, "keep-me.mkv");
  writeFileSync(outside, "x");

  assert.equal(reelDoneAt(allPartsDone), ago(9));
  assert.equal(reelDoneAt(partMissing), null); // a piece was never sent
  assert.equal(reelDoneAt(partFailed), null);

  retentionSweep(NOW);
  for (const gone of [oldReel, neverSent, allPartsDone]) assert.equal(existsSync(gone), false, `${gone} should be removed`);
  for (const kept of [recentReel, young, partMissing, partFailed, notARecording, outside]) assert.equal(existsSync(kept), true, `${kept} should be kept`);
});
