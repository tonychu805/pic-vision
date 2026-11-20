import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

process.env.HOME = mkdtempSync(path.join(tmpdir(), "redact-text-"));
process.env.USERPROFILE = process.env.HOME;
const { redactCredentials, lastStderrLine } = await import("./redactText.js");
const { grabSnapshot } = await import("./capture.js");
const { logEvent, getEvents } = await import("./activityLog.js");

const SECRET = "s3cr3t@Pw";
const REFUSED = `rtsp://picvisionai:${SECRET}@192.168.2.3:554/1: Connection refused`;

test("a camera password in ffmpeg's error line is not kept", () => {
  assert.doesNotMatch(lastStderrLine(`Input #0\n${REFUSED}\n`, "x"), /s3cr3t/);
  assert.doesNotMatch(JSON.stringify(redactCredentials({ error: REFUSED, nested: [REFUSED] })), /s3cr3t/);
  assert.equal(redactCredentials("http://10.0.0.5/onvif?user=admin&password=hunter2 timed out"), "http://10.0.0.5/onvif?user=admin&password=*** timed out");
});

test("the error still says what failed and where", () => {
  assert.equal(lastStderrLine(`Input #0\n${REFUSED}\n`, "x"), "rtsp://***:***@192.168.2.3:554/1: Connection refused");
  assert.equal(lastStderrLine("rtsp://192.168.2.3:554/1: Connection refused", "x"), "rtsp://192.168.2.3:554/1: Connection refused");
  assert.equal(lastStderrLine("", "ffmpeg exited (code 1)"), "ffmpeg exited (code 1)");
  const ok = { outDir: "/Users/x/2026-11-20T08-33-30-916Z", startedAt: "2026-11-20T08:33:30Z", stopped: true };
  assert.deepEqual(redactCredentials(ok), ok);
});

// A real ffmpeg run against a camera that is not there. What its last line says
// depends on the build and the OS (Windows retries the connection until the
// snapshot times out and ends on a version banner), so this checks only that no
// password comes out; the wording checks above use fixed lines.
test("a real failed camera connection never reports the password", async () => {
  const camera = { id: "redact-live", streamUri: "rtsp://127.0.0.1:9/stream1", username: "picvisionai", password: SECRET };
  const err = await grabSnapshot(camera).then(() => null, (e) => e);
  assert.ok(err, "the snapshot fails: nothing listens on port 9");
  assert.ok(err.message.trim(), "the error has a message");
  assert.doesNotMatch(err.message, /s3cr3t/);
});

test("the Log tab never stores a password, and still shows the message", () => {
  logEvent("recording_failed", "Recording failed", REFUSED);
  const [event] = getEvents();
  assert.doesNotMatch(JSON.stringify(event), /s3cr3t/);
  assert.equal(event.detail, "rtsp://***:***@192.168.2.3:554/1: Connection refused");
});

test("a password saved in the Log tab by an older version is cleaned at startup", async () => {
  const { default: Store } = await import("electron-store");
  const saved = new Store({ name: "activityLog" });
  saved.set("events", [{ id: "old", type: "recording_failed", title: "Recording failed", detail: REFUSED, at: "2026-09-29T16:37:08Z" }]);
  const { scrubStoredEvents } = await import("./activityLog.js");
  scrubStoredEvents(saved);
  assert.doesNotMatch(JSON.stringify(saved.get("events")), /s3cr3t/);
  assert.equal(saved.get("events")[0].detail, "rtsp://***:***@192.168.2.3:554/1: Connection refused");
  assert.equal(saved.get("events")[0].id, "old");
});
