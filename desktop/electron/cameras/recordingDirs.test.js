// Recording directories are keyed by camera id, not label (2026-09-18).
//
// The bug: `listRecordings` and `startRecording` both derived the directory
// from the camera's *label*, so renaming a camera pointed them at a
// directory that didn't exist yet. Every past recording vanished from that
// camera's page, along with the "Send to cloud" row for it, while the files
// sat on disk under the old name. Found by UAT on desktop 1.3.0; the same
// label-keying had already caused one real bug (the Court 3 sample clip).
//
// These cover the migration off the old layout, because that is where the
// judgement calls are -- the id-keyed path itself is one `path.join`.
import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { RECORDINGS_ROOT, cameraRecordingsDir } from "../capture.js";
import { planRecordingDirMigration } from "./store.js";

const dir = (...parts) => path.join(RECORDINGS_ROOT, ...parts);
const existsIn = (...paths) => {
  const set = new Set(paths);
  return (p) => set.has(p);
};

test("a camera's directory follows its id, so a rename cannot move it", () => {
  const camera = { id: "cam-1", label: "Court 1" };
  const before = cameraRecordingsDir(camera);
  const after = cameraRecordingsDir({ ...camera, label: "Court 7 (back)" });
  assert.equal(before, after);
  assert.equal(after, dir("cam-1"));
});

test("a directory left by the old layout is moved to its camera's id", () => {
  const cameras = [{ id: "cam-1", label: "Court 1" }];
  const plan = planRecordingDirMigration(cameras, existsIn(dir("Court_1")));
  assert.deepEqual(plan, [{ cameraId: "cam-1", from: dir("Court_1"), to: dir("cam-1") }]);
});

test("nothing to move when the camera never recorded", () => {
  const plan = planRecordingDirMigration([{ id: "cam-1", label: "Court 1" }], existsIn());
  assert.deepEqual(plan, []);
});

test("an already-migrated camera is left alone", () => {
  // Otherwise a second launch would move a same-labelled directory on top
  // of the real one -- renameSync onto an existing directory either throws
  // or, worse, replaces it.
  const cameras = [{ id: "cam-1", label: "Court 1" }];
  const plan = planRecordingDirMigration(cameras, existsIn(dir("cam-1"), dir("Court_1")));
  assert.deepEqual(plan, []);
});

test("two cameras sharing a label: the first takes the directory, the second gets nothing", () => {
  // The old layout let this happen, and the recordings inside are
  // commingled with no way to tell them apart afterwards. Guessing a split
  // would be inventing attribution, so the second camera simply starts
  // fresh rather than both claiming the same directory.
  const cameras = [
    { id: "cam-1", label: "Court 3" },
    { id: "cam-2", label: "Court 3" },
  ];
  const plan = planRecordingDirMigration(cameras, existsIn(dir("Court_3")));
  assert.equal(plan.length, 1);
  assert.equal(plan[0].cameraId, "cam-1");
});

test("a sample clip's stored path is rewritten to follow its directory", () => {
  // sampleClipPath is absolute and stored on the camera. Moving the
  // directory without rewriting it leaves the camera pointing at a file
  // that no longer exists -- listRecordings returns nothing for a sample
  // clip whose file is missing, so the camera would look empty.
  const cameras = [{
    id: "cam-1",
    label: "Court 4",
    connectionType: "sampleClip",
    sampleClipPath: dir("Court_4", "sample-clip.MOV"),
  }];
  const plan = planRecordingDirMigration(cameras, existsIn(dir("Court_4")));
  assert.equal(plan[0].sampleClipPath, dir("cam-1", "sample-clip.MOV"));
});

test("a clip stored outside the directory being moved is not rewritten", () => {
  const cameras = [{
    id: "cam-1",
    label: "Court 4",
    connectionType: "sampleClip",
    sampleClipPath: "/home/someone/Videos/clip.mp4",
  }];
  const plan = planRecordingDirMigration(cameras, existsIn(dir("Court_4")));
  assert.equal(plan[0].sampleClipPath, undefined);
});

test("a label that already sanitises to the camera's id is not moved onto itself", () => {
  const cameras = [{ id: "cam-1", label: "cam-1" }];
  const plan = planRecordingDirMigration(cameras, existsIn(dir("cam-1")));
  assert.deepEqual(plan, []);
});
