// capture.js's recording lifecycle, run for real: real ffmpeg, real
// processes, real signals. The "camera" is a local port that accepts the
// connection and never answers, so ffmpeg sits waiting for a stream exactly
// as it would on a slow camera -- no real camera, stream or frame is ever
// involved (this project's standing rule).
import assert from "node:assert/strict";
import { test, before, after } from "node:test";
import { createServer } from "node:net";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Recordings land under $HOME/pic-vision-recordings; keep them out of the
// real one. Set before capture.js loads, since it reads HOME once.
const home = mkdtempSync(path.join(tmpdir(), "capture-lifecycle-"));
process.env.HOME = home;
const { startRecording, stopRecording, isRecording, activeRecordingDirs, cleanUpOrphanedRecordings } = await import("./capture.js");

// Two independent silent "cameras" -- a dual-stream camera's main and sub
// profiles are two different RTSP URLs, which in reality means two
// different ffmpeg connections even against the same physical device.
let silentCamera, silentSubCamera;
let port, subPort;
before(async () => {
  silentCamera = createServer((socket) => socket.on("error", () => {}));
  await new Promise((r) => silentCamera.listen(0, "127.0.0.1", r));
  port = silentCamera.address().port;

  silentSubCamera = createServer((socket) => socket.on("error", () => {}));
  await new Promise((r) => silentSubCamera.listen(0, "127.0.0.1", r));
  subPort = silentSubCamera.address().port;
});
after(() => {
  silentCamera.close();
  silentSubCamera.close();
  rmSync(home, { recursive: true, force: true });
});

const camera = (id) => ({
  id, label: id, connectionType: "rtsp",
  streamUri: `rtsp://127.0.0.1:${port}/stream`,
  profile: { fps: 30, measuredFps: 30 },
});

// Same as camera(), plus a sub-stream profile (Stage 1 of the dual-stream
// plan: ONVIF-resolved) -- startRecording gates concurrent dual capture
// purely on subStreamUri's presence, so this is all that's needed to
// exercise that path for real.
const dualStreamCamera = (id) => ({
  ...camera(id),
  subStreamUri: `rtsp://127.0.0.1:${subPort}/sub`,
  subProfile: { fps: 30, measuredFps: 30, width: 1280, height: 720 },
});

test("two stops at once: exactly one of them gets the recording", async () => {
  const cam = camera("two-stops");
  const { outDir } = await startRecording(cam);
  const [a, b] = await Promise.all([stopRecording(cam.id), stopRecording(cam.id)]);
  assert.deepEqual([a.stopped, b.stopped].sort(), [false, true]);
  assert.equal((a.stopped ? a : b).outDir, outDir);
  assert.equal(isRecording(cam.id), false);
});

// Paired with the above: a single ordinary stop must still report stopping.
test("a single stop still reports that it stopped the recording", async () => {
  const cam = camera("one-stop");
  const { outDir } = await startRecording(cam);
  const result = await stopRecording(cam.id);
  assert.equal(result.stopped, true);
  assert.equal(result.outDir, outDir);
});

test("resuming after a restart carries on in the same folder", async () => {
  const cam = camera("resume");
  const first = await startRecording(cam);
  await stopRecording(cam.id);
  const resumed = await startRecording(cam, { resumeInto: first.outDir });
  assert.equal(resumed.outDir, first.outDir);
  await stopRecording(cam.id);
});

// A stand-in for a recording a crashed app left running: a live process
// whose command line names the recording's folder, like ffmpeg's does.
function fakeOrphan(outDir) {
  return spawn(process.execPath, ["-e", "process.on('SIGINT', () => process.exit(0)); setInterval(() => {}, 1000)", outDir], { stdio: "ignore" });
}
const exited = (proc) => new Promise((r) => (proc.exitCode !== null || proc.signalCode !== null ? r() : proc.once("exit", r)));

test("a recording left running by a crash is stopped at the next launch", async () => {
  const outDir = path.join(home, "orphan-recording");
  const orphan = fakeOrphan(outDir);
  await new Promise((r) => setTimeout(r, 200));
  const stopped = await cleanUpOrphanedRecordings({ graceMs: 5000, entries: { cam: { main: { pid: orphan.pid, outDir } } } });
  await exited(orphan);
  assert.deepEqual(stopped, [{ cameraId: "cam", outDir }]);
  assert.equal(orphan.signalCode ?? orphan.exitCode, 0); // clean SIGINT exit, not a hard kill
});

// Paired: process numbers get reused. A live process that ISN'T our
// recording -- its command line doesn't name the folder -- must be left alone.
test("a process that merely reuses a recorded process number is left alone", async () => {
  const unrelated = fakeOrphan(path.join(home, "something-else"));
  await new Promise((r) => setTimeout(r, 200));
  try {
    const stopped = await cleanUpOrphanedRecordings({ graceMs: 1000, entries: { cam: { main: { pid: unrelated.pid, outDir: path.join(home, "orphan-recording") } } } });
    assert.deepEqual(stopped, []);
    assert.equal(unrelated.exitCode, null);
    assert.ok(existsSync(home));
  } finally {
    unrelated.kill("SIGKILL");
  }
});

// Stage 2 of the dual-stream plan: a camera with a resolved sub-profile
// records both streams concurrently, into separate sibling folders, and
// both must be protected from cleanup while the recording is active --
// not just the main one, which is all any single-stream camera ever had.
test("a dual-stream camera records both streams into separate protected folders", async () => {
  const cam = dualStreamCamera("dual-start");
  const { outDir } = await startRecording(cam);
  const subOutDir = `${outDir}-sub`;
  assert.ok(existsSync(outDir));
  assert.ok(existsSync(subOutDir));
  const dirs = activeRecordingDirs();
  assert.ok(dirs.has(outDir));
  assert.ok(dirs.has(subOutDir));
  await stopRecording(cam.id);
});

// Paired with the above: stopping the camera has to stop BOTH ffmpeg
// processes, not just main's -- otherwise a sub-stream recording would
// keep running forever every time a dual-stream camera's session ends.
test("stopping a dual-stream camera stops both streams and frees both folders", async () => {
  const cam = dualStreamCamera("dual-stop");
  const { outDir } = await startRecording(cam);
  const subOutDir = `${outDir}-sub`;
  const result = await stopRecording(cam.id);
  assert.equal(result.stopped, true);
  assert.equal(isRecording(cam.id), false);
  const dirs = activeRecordingDirs();
  assert.ok(!dirs.has(outDir));
  assert.ok(!dirs.has(subOutDir));
});

// A camera with no sub-profile (every camera in production today) must
// behave exactly as before Stage 2 -- no sibling folder, no second
// process, activeRecordingDirs() reports only the one folder it always did.
test("a single-stream camera is unaffected: no sibling folder, no second process", async () => {
  const cam = camera("single-only");
  const { outDir } = await startRecording(cam);
  assert.ok(!existsSync(`${outDir}-sub`));
  assert.deepEqual([...activeRecordingDirs()], [outDir]);
  await stopRecording(cam.id);
});
