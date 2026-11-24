// PGC, 2026-11-24: parts 3-12 of a session read "Uploading..." for hours.
// Nothing was uploading: the send never reached the console, nothing wrote
// that down, and Cancel had no cloud job to cancel, so it did nothing. The
// venue PC's log also showed EPERM on renaming cloud_job/status.json, thrown
// from inside the upload stream.
//
// Real pipeline.js against a local HTTP server standing in for the console.
// Paired: each failure path sits beside the path that must keep working.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test, before, after } from "node:test";
import { renameWithRetry } from "./atomicFile.js";
import { putStream } from "./consoleApi.js";
import { syntheticBody } from "./bandwidth.js";

const { registerAgentOnce, stopHeartbeatLoop, disconnectCloud } = await import("./cloud.js");
const { runCloudJob, cancelCloudJob, pipelineStatus } = await import("./pipeline.js");
const { unsentParts } = await import("./autoSplit.js");

const eperm = () => Object.assign(new Error("EPERM: operation not permitted, rename"), { code: "EPERM" });

test("a rename Windows refuses for a moment is retried until it goes through", () => {
  let calls = 0;
  renameWithRetry("a", "b", { waitMs: 1, rename: () => { if (++calls < 3) throw eperm(); } });
  assert.equal(calls, 3);
});

test("a rename that keeps failing, or fails for another reason, still throws", () => {
  let calls = 0;
  assert.throws(() => renameWithRetry("a", "b", { waitMs: 1, attempts: 4, rename: () => { calls++; throw eperm(); } }), /EPERM/);
  assert.equal(calls, 4);
  calls = 0;
  const missing = Object.assign(new Error("ENOENT"), { code: "ENOENT" });
  assert.throws(() => renameWithRetry("a", "b", { rename: () => { calls++; throw missing; } }), /ENOENT/);
  assert.equal(calls, 1, "not a Windows lock: no retry");
});

// The upload itself: a progress callback that throws must not cost the
// transfer any bytes. Before the fix the throw skipped piping that chunk and
// the request stalled short of its Content-Length.
async function receivedBy(run) {
  let received = 0;
  const server = createServer((req, res) => {
    req.on("data", (c) => { received += c.length; });
    req.on("end", () => { res.writeHead(200); res.end(); });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    await run(`http://127.0.0.1:${server.address().port}/put`);
    return received;
  } finally {
    server.closeAllConnections?.();
    server.close();
  }
}

test("an upload whose progress report throws still sends every byte", { timeout: 15_000 }, async () => {
  const total = 4 * 1024 * 1024;
  let reports = 0;
  const received = await receivedBy((url) => putStream(url, syntheticBody(total), total, () => { reports++; throw eperm(); }, undefined, 3_000));
  assert.ok(reports > 1, "the callback ran on more than one chunk");
  assert.equal(received, total);
});

test("an upload with a working progress report sends every byte", { timeout: 15_000 }, async () => {
  const total = 4 * 1024 * 1024;
  const received = await receivedBy((url) => putStream(url, syntheticBody(total), total, () => {}, undefined, 3_000));
  assert.equal(received, total);
});

// The send itself, against a fake console.
let server;
let root;
let jobsAnswer = 503;

before(async () => {
  root = mkdtempSync(path.join(os.tmpdir(), "stuck-upload-"));
  server = createServer((req, res) => {
    req.on("data", () => {});
    req.on("end", () => {
      if (req.method === "POST" && req.url === "/api/agents/jobs") {
        res.writeHead(jobsAnswer, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: jobsAnswer === 400 ? "this camera has not been calibrated yet" : "unavailable" }));
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(req.url.includes("register")
        ? { agentId: "agent-1", apiToken: "tok", brandName: "Test Venue" }
        : { brandName: "Test Venue", cameras: [] }));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  await registerAgentOnce("access-token", "user-1", `http://127.0.0.1:${server.address().port}`);
  stopHeartbeatLoop();
});

after(() => {
  disconnectCloud();
  rmSync(root, { recursive: true, force: true });
  server.closeAllConnections();
  server.close();
});

let n = 0;
/** A recording with one cut part, as autoSplit.js leaves it. */
function recordingWithPart() {
  const rec = path.join(root, `rec-${++n}`);
  const part = path.join(rec, "parts", "part-01");
  mkdirSync(part, { recursive: true });
  writeFileSync(path.join(part, "session-000.mkv"), "video");
  return { rec, part };
}
const stage = (dir) => pipelineStatus(path.join(dir, "cloud_job")).stage;

test("a send the console never answered is marked to retry, and the sweep would send it again", async () => {
  jobsAnswer = 503;
  const { rec, part } = recordingWithPart();
  await assert.rejects(runCloudJob({ recordingDir: part, sessionId: "s", cameraId: "c", cameraLabel: "Court A" }));
  assert.equal(stage(part), "retry", "not left at \"upload\"");
  assert.equal(existsSync(path.join(part, "cloud_job", "job.json")), false);
  assert.deepEqual(unsentParts(rec, () => false).map((p) => p.name), ["part-01"]);
});

test("a send the console refuses is a failure, not a retry", async () => {
  jobsAnswer = 400;
  const { rec, part } = recordingWithPart();
  await assert.rejects(runCloudJob({ recordingDir: part, sessionId: "s", cameraId: "c", cameraLabel: "Court A" }));
  assert.equal(stage(part), "error");
  assert.deepEqual(unsentParts(rec, () => true), [], "nothing sends it again on its own");
});

test("Cancel on a part waiting to retry marks it cancelled, and the sweep leaves it", async () => {
  jobsAnswer = 503;
  const { rec, part } = recordingWithPart();
  await assert.rejects(runCloudJob({ recordingDir: part, sessionId: "s", cameraId: "c", cameraLabel: "Court A" }));
  assert.deepEqual(await cancelCloudJob(part), { cancelled: true, stopped: true });
  assert.equal(stage(part), "cancelled");
  assert.deepEqual(unsentParts(rec, () => false), []);
});

test("Cancel on a part left at \"uploading\" with no cloud job (the PGC rows) marks it cancelled", async () => {
  const { part } = recordingWithPart();
  mkdirSync(path.join(part, "cloud_job"), { recursive: true });
  writeFileSync(path.join(part, "cloud_job", "status.json"), JSON.stringify({ stage: "upload", message: "preparing upload..." }));
  assert.deepEqual(await cancelCloudJob(part), { cancelled: true, stopped: true });
  assert.equal(JSON.parse(readFileSync(path.join(part, "cloud_job", "status.json"), "utf8")).stage, "cancelled");
});

test("Cancel on a part with nothing sent and nothing pending still does nothing", async () => {
  const { part } = recordingWithPart();
  assert.deepEqual(await cancelCloudJob(part), { cancelled: false });
  assert.equal(stage(part), null);
});
