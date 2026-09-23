import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, writeFileSync, utimesSync, mkdirSync, statSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { planParts, finishedSegments, makeDueParts, listParts, unsentParts, partSessionId, SETTLE_MS, writeSessionMeta, sessionFieldsFor } from "./autoSplit.js";

const seg = (i) => `session-${String(i).padStart(3, "0")}.mkv`;

test("planParts: whole parts only while recording; a flush sends whatever is finished", () => {
  const finished = [seg(0), seg(1), seg(2), seg(3), seg(4)];
  assert.deepEqual(planParts({ finished, sent: new Set(), partSegments: 2, flush: false }), [[seg(0), seg(1)], [seg(2), seg(3)]]);
  assert.deepEqual(planParts({ finished, sent: new Set([seg(0), seg(1)]), partSegments: 2, flush: false }), [[seg(2), seg(3)]]);
  assert.deepEqual(planParts({ finished, sent: new Set([seg(0), seg(1), seg(2), seg(3)]), partSegments: 2, flush: true }), [[seg(4)]]);
  assert.deepEqual(planParts({ finished, sent: new Set(finished), partSegments: 2, flush: true }), []);
});

test("finishedSegments: never the file ffmpeg is still writing, nor one written in the last few seconds", () => {
  const now = 1_000_000;
  const mtimes = { [seg(0)]: now - 600_000, [seg(1)]: now - 5_000, [seg(2)]: now - 1_000 };
  const names = [seg(2), seg(0), seg(1), "other.txt"];
  // Recording: seg 2 is being written; seg 1 only just closed -> wait.
  assert.deepEqual(finishedSegments(names, { stillRecording: true, mtimes, now }), [seg(0)]);
  assert.deepEqual(finishedSegments(names, { stillRecording: true, mtimes, now: now + SETTLE_MS }), [seg(0), seg(1)]);
  // Stopped: every segment is final, including the last.
  assert.deepEqual(finishedSegments(names, { stillRecording: false, mtimes, now }), [seg(0), seg(1), seg(2)]);
});

function recording(segments, { ageMs = 60_000 } = {}) {
  const dir = mkdtempSync(path.join(tmpdir(), "autosplit-"));
  const t = (Date.now() - ageMs) / 1000;
  for (let i = 0; i < segments; i++) {
    const f = path.join(dir, seg(i));
    writeFileSync(f, `segment ${i}`);
    utimesSync(f, t, t);
  }
  return dir;
}

test("a 2-hour recording in 20-minute parts: every segment sent exactly once, in order, the last on stop", () => {
  const dir = recording(12); // 12 x 10 min
  // During recording (segment 11 still being written): 5 whole parts of 2.
  const during = makeDueParts(dir, { stillRecording: true, partMinutes: 20 });
  assert.deepEqual(during.map((p) => p.segments), [[seg(0), seg(1)], [seg(2), seg(3)], [seg(4), seg(5)], [seg(6), seg(7)], [seg(8), seg(9)]]);
  // Another tick with nothing new: nothing more.
  assert.equal(makeDueParts(dir, { stillRecording: true, partMinutes: 20 }).length, 0);
  // Stop: the rest goes as the final part, even though it's a partial part.
  const final = makeDueParts(dir, { stillRecording: false, partMinutes: 20, flush: true });
  assert.deepEqual(final.map((p) => p.segments), [[seg(10), seg(11)]]);
  const all = listParts(dir).flatMap((p) => p.segments);
  assert.deepEqual(all, Array.from({ length: 12 }, (_, i) => seg(i)), "each segment exactly once, in order");
  assert.deepEqual(listParts(dir).map((p) => p.name), ["part-01", "part-02", "part-03", "part-04", "part-05", "part-06"]);
});

test("10-minute parts: each segment goes on its own as soon as it's finished", () => {
  const dir = recording(4); // segment 3 still being written
  const during = makeDueParts(dir, { stillRecording: true, partMinutes: 10 });
  assert.deepEqual(during.map((p) => p.segments), [[seg(0)], [seg(1)], [seg(2)]]);
  assert.equal(makeDueParts(dir, { stillRecording: true, partMinutes: 10 }).length, 0);
  const final = makeDueParts(dir, { stillRecording: false, partMinutes: 10, flush: true });
  assert.deepEqual(final.map((p) => p.segments), [[seg(3)]]);
  assert.deepEqual(listParts(dir).map((p) => p.name), ["part-01", "part-02", "part-03", "part-04"]);
  writeSessionMeta(dir, { recording_session_id: "22222222-2222-4222-8222-222222222222" });
  assert.deepEqual(listParts(dir).map((p) => sessionFieldsFor(p.dir, p.segments).partOffsetSec), [0, 600, 1200, 1800]);
});

test("parts are hard links: no copy of the footage, and the recording itself is untouched", () => {
  const dir = recording(2);
  const [part] = makeDueParts(dir, { stillRecording: false, partMinutes: 20, flush: true });
  assert.equal(statSync(path.join(part.dir, seg(0))).ino, statSync(path.join(dir, seg(0))).ino);
  assert.deepEqual(readdirSync(dir).filter((f) => f.endsWith(".mkv")).sort(), [seg(0), seg(1)]);
});

test("send now mid-recording: everything finished goes, the file being written stays", () => {
  const dir = recording(3);
  const [part] = makeDueParts(dir, { stillRecording: true, partMinutes: 30, flush: true });
  assert.deepEqual(part.segments, [seg(0), seg(1)]);
});

test("a part whose send never reached the console is found for a resend -- but not while it's being sent", () => {
  const dir = recording(4);
  const [p1, p2] = makeDueParts(dir, { stillRecording: false, partMinutes: 20 });
  mkdirSync(path.join(p1.dir, "cloud_job"), { recursive: true });
  writeFileSync(path.join(p1.dir, "cloud_job", "job.json"), JSON.stringify({ jobId: "j1" }));
  assert.deepEqual(unsentParts(dir, () => false).map((p) => p.name), [p2.name]);
  assert.deepEqual(unsentParts(dir, (d) => d === p2.dir), [], "an in-flight part must not be sent twice");
});

test("every part gets its own session id (the console cancels an older upload of the same session)", () => {
  const a = partSessionId("Court 5", "/rec/2026-09-26T10-00-00-000Z", "part-01");
  const b = partSessionId("Court 5", "/rec/2026-09-26T10-00-00-000Z", "part-02");
  assert.notEqual(a, b);
  assert.match(a, /^[a-zA-Z0-9._-]+$/);
});


test("session fields: a part carries the session, its number, and where it starts; a whole recording just the session", () => {
  const dir = recording(6);
  writeSessionMeta(dir, { recording_session_id: "11111111-1111-4111-8111-111111111111", schedule_booking_id: "b-1" });
  const [p1, p2] = makeDueParts(dir, { stillRecording: false, partMinutes: 20 });
  assert.deepEqual(sessionFieldsFor(p1.dir, p1.segments), { recordingSessionId: "11111111-1111-4111-8111-111111111111", partIndex: 1, partOffsetSec: 0 });
  assert.deepEqual(sessionFieldsFor(p2.dir, p2.segments), { recordingSessionId: "11111111-1111-4111-8111-111111111111", partIndex: 2, partOffsetSec: 1200 });
  assert.deepEqual(sessionFieldsFor(dir, [seg(0)]), { recordingSessionId: "11111111-1111-4111-8111-111111111111" });
});

test("session fields: a recording from before sessions (or a start without one) sends nothing extra", () => {
  const old = recording(2);
  assert.deepEqual(sessionFieldsFor(old, [seg(0)]), {});
  const none = recording(2);
  writeSessionMeta(none, {});
  const [p] = makeDueParts(none, { stillRecording: false, partMinutes: 20, flush: true });
  assert.deepEqual(sessionFieldsFor(p.dir, p.segments), {});
});
