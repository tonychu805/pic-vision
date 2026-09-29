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
const { startRecording, stopRecording, isRecording, cleanUpOrphanedRecordings } = await import("./capture.js");

let silentCamera;
let port;
before(async () => {
  silentCamera = createServer((socket) => socket.on("error", () => {}));
  await new Promise((r) => silentCamera.listen(0, "127.0.0.1", r));
  port = silentCamera.address().port;
});
after(() => {
  silentCamera.close();
  rmSync(home, { recursive: true, force: true });
});

const camera = (id) => ({
  id, label: id, connectionType: "rtsp",
  streamUri: `rtsp://127.0.0.1:${port}/stream`,
  profile: { fps: 30, measuredFps: 30 },
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
  const stopped = await cleanUpOrphanedRecordings({ graceMs: 5000, entries: { cam: { pid: orphan.pid, outDir } } });
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
    const stopped = await cleanUpOrphanedRecordings({ graceMs: 1000, entries: { cam: { pid: unrelated.pid, outDir: path.join(home, "orphan-recording") } } });
    assert.deepEqual(stopped, []);
    assert.equal(unrelated.exitCode, null);
    assert.ok(existsSync(home));
  } finally {
    unrelated.kill("SIGKILL");
  }
});
