// The venue computer's recording cleanup (recordingRetention.js).
import assert from "node:assert/strict";
import { test, after } from "node:test";
import { mkdirSync, mkdtempSync, writeFileSync, existsSync, rmSync, linkSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Recordings live under $HOME/pic-vision-recordings, read once at load.
const home = mkdtempSync(path.join(tmpdir(), "retention-"));
process.env.HOME = home;
const { retentionDecision, retentionSweep, retentionSummary, reelDoneAt, recordingStartedAt, endOfVenueDay } = await import("./recordingRetention.js");
after(() => rmSync(home, { recursive: true, force: true }));

const DAY = 86_400_000;
const NOW = Date.parse("2026-09-29T12:00:00.000Z");
const ago = (days) => NOW - days * DAY;
const TIMEZONE = "Asia/Taipei";

test("a reel ready before the venue-local day ends is deleted at midnight", () => {
  const endedAt = Date.parse("2026-09-29T10:00:00.000Z"); // 18:00 Taipei
  const deleteAt = endOfVenueDay(endedAt, TIMEZONE);
  assert.equal(new Date(deleteAt).toISOString(), "2026-09-29T16:00:00.000Z");
  assert.equal(retentionDecision({ endedAt, doneAt: endedAt, busy: false, timezone: TIMEZONE }, deleteAt - 1).action, "keep");
  assert.equal(retentionDecision({ endedAt, doneAt: endedAt, busy: false, timezone: TIMEZONE }, deleteAt).action, "delete");
});

test("a reel that succeeds after its local day ends deletes promptly", () => {
  const endedAt = Date.parse("2026-09-28T10:00:00.000Z");
  assert.equal(retentionDecision({ endedAt, doneAt: NOW, busy: false, timezone: TIMEZONE }, NOW).action, "delete");
});

test("a failed or unsent recording stays past midnight until its reel succeeds", () => {
  const result = retentionDecision({ endedAt: ago(2), doneAt: null, busy: false, timezone: TIMEZONE }, NOW);
  assert.equal(result.action, "keep");
  assert.equal(result.reason, "waiting for reel after end of day");
});

// Paired with every delete above: nothing in use is ever removed.
test("a recording in progress, or uploading, is never removed", () => {
  assert.equal(retentionDecision({ endedAt: ago(60), doneAt: ago(50), busy: true, timezone: TIMEZONE }, NOW).action, "keep");
  assert.equal(retentionDecision({ endedAt: ago(60), doneAt: null, busy: true, timezone: TIMEZONE }, NOW).action, "keep");
});

test("an invalid or missing venue timezone keeps footage rather than guessing", () => {
  assert.equal(retentionDecision({ endedAt: ago(1), doneAt: ago(1), busy: false, timezone: null }, NOW).action, "keep");
  assert.equal(retentionDecision({ endedAt: ago(1), doneAt: ago(1), busy: false, timezone: "not/a-timezone" }, NOW).reason, "venue timezone unavailable");
});

test("the end day follows the last captured segment, not a before-midnight start", () => {
  const startedAt = Date.parse("2026-09-29T15:50:00.000Z"); // 23:50 Taipei
  const endedAt = Date.parse("2026-09-29T16:10:00.000Z"); // 00:10 next day
  assert.equal(new Date(endOfVenueDay(endedAt, TIMEZONE)).toISOString(), "2026-09-30T16:00:00.000Z");
  assert.ok(endOfVenueDay(endedAt, TIMEZONE) > endOfVenueDay(startedAt, TIMEZONE));
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
  for (let i = 0; i < 3; i++) {
    const file = path.join(dir, `session-00${i}.mkv`);
    writeFileSync(file, "x");
    utimesSync(file, ago(startedDaysAgo) / 1000, ago(startedDaysAgo) / 1000);
  }
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
    const main = path.join(dir, `session-00${i}.mkv`);
    const sub = path.join(subDir, `session-00${i}.mkv`);
    writeFileSync(main, "x");
    writeFileSync(sub, "x");
    utimesSync(main, ago(startedDaysAgo) / 1000, ago(startedDaysAgo) / 1000);
    utimesSync(sub, ago(startedDaysAgo) / 1000, ago(startedDaysAgo) / 1000);
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
  retentionSweep({ now: NOW, timezone: TIMEZONE });
  assert.equal(existsSync(dir), false, "main should be removed");
  assert.equal(existsSync(subDir), false, "its sub-stream sibling should go with it, not be left behind");
});

// Paired: a dual-stream recording still waiting on its reel (or too young
// to be due) keeps BOTH folders -- the sub sibling is never independently
// evaluated on its own schedule, since RECORDING_DIR_RE never matches it.
test("a dual-stream recording waiting for its reel keeps both folders", () => {
  const { dir, subDir } = dualStreamRecording("cam-dual-young", 5);
  retentionSweep({ now: NOW, timezone: TIMEZONE });
  assert.equal(existsSync(dir), true);
  assert.equal(existsSync(subDir), true);
});

test("the heartbeat summary distinguishes delete-tonight from footage held for a reel without deleting either", () => {
  const deletesTonight = recording("cam-summary", 0, { doneDaysAgo: 0 });
  const heldForReel = recording("cam-summary", 4);
  const summary = retentionSummary({ now: NOW, timezone: TIMEZONE })["cam-summary"];
  assert.equal(summary.waitingAfterEndOfDay, 1);
  assert.equal(summary.waitingForReel, 0);
  assert.equal(typeof summary.deletesAt, "number");
  assert.equal(existsSync(deletesTonight), true);
  assert.equal(existsSync(heldForReel), true);
});

test("a sweep removes exactly the recordings the rules say, and nothing else", () => {
  const oldReel = recording("cam-1", 12, { doneDaysAgo: 8 });
  const recentReel = recording("cam-1", 0, { doneDaysAgo: 0 });
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

  retentionSweep({ now: NOW, timezone: TIMEZONE });
  for (const gone of [oldReel, allPartsDone]) assert.equal(existsSync(gone), false, `${gone} should be removed`);
  for (const kept of [recentReel, neverSent, young, partMissing, partFailed, notARecording, outside]) assert.equal(existsSync(kept), true, `${kept} should be kept`);
});
