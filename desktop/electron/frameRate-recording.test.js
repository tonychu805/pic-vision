// The frame-rate rule (ADR-170) through the real recording path: a frame
// rate measured by the app's own probe from a real 15 fps video, fed into a
// real startRecording that spawns real ffmpeg. The "camera" is a local port
// that accepts and never answers, as in capture-lifecycle.test.js; the video
// is ffmpeg's synthetic test pattern, so no real camera or frame is involved.
import assert from "node:assert/strict";
import { test, before, after } from "node:test";
import { createServer } from "node:net";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const home = mkdtempSync(path.join(tmpdir(), "framerate-recording-"));
process.env.HOME = home;
process.env.USERPROFILE = home;
const { startRecording, stopRecording, isRecording, measureStreamProfile } = await import("./capture.js");
const { FFMPEG } = await import("./binaries.js");
const { needsCheckBeforeStart } = await import("./cameras/measureSchedule.js");

let silentCamera, port, arriving;
before(async () => {
  silentCamera = createServer((socket) => socket.on("error", () => {}));
  await new Promise((r) => silentCamera.listen(0, "127.0.0.1", r));
  port = silentCamera.address().port;
  const clip = path.join(home, "fifteen.mp4");
  const made = spawnSync(FFMPEG, ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", clip]);
  assert.equal(made.status, 0, String(made.stderr));
  arriving = (await measureStreamProfile(clip))?.fps;
});
after(() => {
  silentCamera.close();
  rmSync(home, { recursive: true, force: true });
});

const camera = (id, configured) => ({
  id, label: id, connectionType: "rtsp",
  streamUri: `rtsp://127.0.0.1:${port}/stream`,
  profile: { fps: configured, measuredFps: arriving },
});

test("the app's probe reads a 15 fps video as 15 fps", () => {
  assert.ok(Math.abs(arriving - 15) < 0.5, `measured ${arriving}`);
});

test("a camera set to 30 with 15 arriving records, with the network warning", async () => {
  const cam = camera("set-30", 30);
  const started = await startRecording(cam);
  try {
    assert.equal(isRecording(cam.id), true);
    assert.match(started.frameRateWarning, /set to 30 fps but only about 15 fps/);
    assert.match(started.frameRateWarning, /Wi-Fi/);
    assert.equal(needsCheckBeforeStart(cam), false, "a start that goes ahead is not delayed by a fresh check");
  } finally {
    await stopRecording(cam.id);
  }
});

test("a camera set to 15 is refused and nothing is recorded", async () => {
  const cam = camera("set-15", 15);
  await assert.rejects(async () => startRecording(cam), /set the video frame rate to 30/);
  assert.equal(isRecording(cam.id), false);
  assert.equal(needsCheckBeforeStart(cam), true);
});

test("a camera reporting no setting with 15 arriving is refused, and would get a fresh check first", async () => {
  const cam = camera("rtsp-15", null);
  await assert.rejects(async () => startRecording(cam), /is sending about 15 fps/);
  assert.equal(isRecording(cam.id), false);
  assert.equal(needsCheckBeforeStart(cam), true);
});
