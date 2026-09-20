// A job that is alive in the cloud must be FOLLOWED, however the app got
// here.
//
// Reported 2026-09-20: Stop was clicked on a job whose pod never started; the
// job was cancelled on the console, and the desktop row said "Stopping…"
// indefinitely -- with the Cancel button hidden and no Retry, so no way out.
// status.json is only ever advanced by pollUntilDone, which was started from
// exactly two places (an upload finishing, and the Cancel click) and never
// when the app launched. Close or restart the app after sending a job and
// the file froze at whatever it last said.
//
// Real code: the real pipeline.js against a real local HTTP server standing
// in for the console, reading and writing real status files. Own file so it
// runs in its own process; the poll interval is shortened through the env seam
// that has to be set BEFORE pipeline.js loads, hence the dynamic import.
//
// Paired throughout. Every "must resume" sits beside a "must NOT": terminal
// jobs, dead uploads and recordings with nothing to follow. And -- because
// the previous two features today each shipped tests that passed with the
// logic deleted -- each is checked by breaking the implementation.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test, before, after } from "node:test";

process.env.PIC_VISION_POLL_INTERVAL_MS = "40";

const { registerAgentOnce, stopHeartbeatLoop, disconnectCloud } = await import("./cloud.js");
const { pipelineStatusForRecording } = await import("./pipeline.js");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(condition, what, ms = 6000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await condition()) return;
    await sleep(20);
  }
  assert.fail(`timed out waiting for ${what}`);
}

let server;
let root;
// jobId -> { code, job }  what the fake console answers for that job
const jobs = new Map();
// jobId -> number of GET /api/agents/jobs/<id> received
const gets = new Map();

before(async () => {
  root = mkdtempSync(path.join(os.tmpdir(), "pipeline-resume-"));
  server = createServer((req, res) => {
    req.on("data", () => {});
    req.on("end", () => {
      const match = req.method === "GET" && req.url.match(/^\/api\/agents\/jobs\/([^/?]+)/);
      if (match) {
        const id = match[1];
        gets.set(id, (gets.get(id) ?? 0) + 1);
        const { code = 200, job } = jobs.get(id) ?? { code: 404 };
        res.writeHead(code, { "content-type": "application/json" });
        res.end(JSON.stringify(code === 200 ? { job } : { error: code === 404 ? "job not found" : "busy" }));
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
  await sleep(200);
});

after(async () => {
  // End every follower still running. A failed assertion, or a deliberately
  // broken implementation, leaves polling loops behind, and a loop keeps the
  // process alive -- so the run HANGS instead of reporting which test failed.
  // That is exactly what happened while breaking this feature to check these
  // tests: two runs sat until a 150s timeout with no output, which detects the
  // break but attributes it to nothing. Ending them here means a broken
  // implementation fails loudly and quickly. Every job id the console has been
  // asked about is answered "cancelled", including ones it had been answering
  // 404 or 503 for, so a loop that only ends on a terminal answer still ends.
  for (const id of new Set([...jobs.keys(), ...gets.keys()])) {
    jobs.set(id, { code: 200, job: { status: "cancelled", stage: "cancelled", message: "cancelled" } });
  }
  await sleep(500); // ~12 poll intervals at 40ms
  disconnectCloud();
  rmSync(root, { recursive: true, force: true });
  server.closeAllConnections();
  server.close();
});

let n = 0;
/** A recording as the desktop leaves it on disk: a status.json, and (usually) the job id it saved. */
function recording({ stage, message = "", jobId = `job-${++n}`, withJobJson = true }) {
  const dir = path.join(root, `rec-${++n}`);
  mkdirSync(path.join(dir, "cloud_job"), { recursive: true });
  writeFileSync(path.join(dir, "cloud_job", "status.json"), JSON.stringify({ stage, message }));
  if (withJobJson) writeFileSync(path.join(dir, "cloud_job", "job.json"), JSON.stringify({ jobId, label: "Court 4" }));
  return { dir, jobId };
}
const stageOf = (dir) => JSON.parse(readFileSync(path.join(dir, "cloud_job", "status.json"), "utf8")).stage;
const statusOf = (dir) => JSON.parse(readFileSync(path.join(dir, "cloud_job", "status.json"), "utf8"));
const consoleSays = (jobId, job, code = 200) => jobs.set(jobId, { code, job });
const getsFor = (jobId) => gets.get(jobId) ?? 0;

// --- the reported bug --------------------------------------------------------

test("a row frozen at 'Stopping…' is unstuck once the console says cancelled", async () => {
  // The exact state on the operator's screen: local status.json still says
  // cancelling, the console says cancelled, nothing is asking. The renderer
  // reads this every 2s, so the read is what must notice.
  const { dir, jobId } = recording({ stage: "cancelling", message: "stopping..." });
  consoleSays(jobId, { status: "cancelled", stage: "cancelled", message: "cancelled", cancel_requested: true });

  pipelineStatusForRecording(dir); // what the renderer's 2s poll does
  await waitFor(() => stageOf(dir) === "cancelled", "the row to leave 'Stopping…'");
  assert.equal(stageOf(dir), "cancelled");
});

test("a job still running in the cloud is followed to its end, not frozen at its last stage", async () => {
  // The same gap without the cancel: send a job, restart the app, and the
  // progress froze. Following has to CONTINUE through non-terminal states
  // and finish when the job does.
  const { dir, jobId } = recording({ stage: "queued", message: "waiting for processing" });
  consoleSays(jobId, { status: "running", stage: "inference", message: "running inference", progress: { current: 5, total: 10 } });

  pipelineStatusForRecording(dir);
  await waitFor(() => stageOf(dir) === "inference", "the live stage to be mirrored");
  const seen = getsFor(jobId);
  await waitFor(() => getsFor(jobId) > seen + 2, "it to keep polling while the job runs");

  consoleSays(jobId, { status: "done", stage: "done", message: "done", result: { reels: [] } });
  await waitFor(() => stageOf(dir) === "done", "the finished job to be recorded");
});

test("a cancel still in progress on the console keeps showing 'Stopping…', then settles", async () => {
  // The paired half of the fix for the reported row: resuming must not turn
  // an honest "stopping" into a confident stage name, which is what the
  // mirroring logic exists to avoid (a pod asked to stop keeps reporting
  // whatever stage it is on until it actually stops).
  const { dir, jobId } = recording({ stage: "cancelling", message: "stopping..." });
  consoleSays(jobId, { status: "running", stage: "inference", message: "running inference", cancel_requested: true });

  pipelineStatusForRecording(dir);
  const seen = () => getsFor(jobId);
  const first = seen();
  await waitFor(() => seen() > first + 2, "several polls");
  assert.equal(stageOf(dir), "cancelling", "must not flip back to a stage name while a stop is in progress");

  consoleSays(jobId, { status: "cancelled", stage: "cancelled", message: "cancelled", cancel_requested: true });
  await waitFor(() => stageOf(dir) === "cancelled", "it to settle once the console confirms");
});

// --- what must NOT be resumed -------------------------------------------------

test("a finished job is never re-followed", async () => {
  for (const stage of ["done", "cancelled", "error"]) {
    const { dir, jobId } = recording({ stage });
    consoleSays(jobId, { status: "running", stage: "inference" }); // would be visible if it were polled
    pipelineStatusForRecording(dir);
    await sleep(250);
    assert.equal(getsFor(jobId), 0, `a '${stage}' job must not be polled`);
    assert.equal(stageOf(dir), stage);
  }
});

test("a dead upload is not resumed -- the transfer died with the process that was doing it", async () => {
  // Following the console would mirror a job that can never advance, and
  // hide that the upload needs redoing. That is a separate problem; this
  // must not quietly make it look like progress.
  const { dir, jobId } = recording({ stage: "upload", message: "uploading clip (1 of 1)..." });
  consoleSays(jobId, { status: "uploading", stage: "uploading" });
  pipelineStatusForRecording(dir);
  await sleep(250);
  assert.equal(getsFor(jobId), 0);
  assert.equal(stageOf(dir), "upload");
});

test("a recording with nothing to follow neither polls nor throws", async () => {
  const noJobFile = recording({ stage: "queued", withJobJson: false });
  assert.doesNotThrow(() => pipelineStatusForRecording(noJobFile.dir));
  const neverSent = { dir: path.join(root, "never-sent") };
  mkdirSync(neverSent.dir, { recursive: true });
  assert.deepEqual(pipelineStatusForRecording(neverSent.dir), { stage: null });
  await sleep(150);
});

// --- and it must not become a storm ---------------------------------------------

test("reading the status repeatedly starts ONE follower, not one per read", async () => {
  // The renderer reads every 2s per row. Without a guard each read would
  // start another loop against the console.
  const { dir, jobId } = recording({ stage: "queued" });
  consoleSays(jobId, { status: "running", stage: "inference", message: "running" });

  for (let i = 0; i < 25; i++) pipelineStatusForRecording(dir);
  await waitFor(() => stageOf(dir) === "inference", "the follower to start");
  const start = getsFor(jobId);
  await sleep(400); // ~10 poll intervals at 40ms
  const polls = getsFor(jobId) - start;
  // One loop is ~10 requests in that window; 25 would be ~250.
  assert.ok(polls <= 20, `expected a single follower (~10 polls in the window), saw ${polls}`);

  consoleSays(jobId, { status: "done", stage: "done", message: "done" });
  await waitFor(() => stageOf(dir) === "done", "the loop to end");
});

test("a job the console says does not exist stops the polling and says so", async () => {
  // Otherwise: a cloud-function call every few seconds, forever, per row,
  // for a job that is not there. That is how idle polling exhausted the
  // Netlify quota and took every public site down for five days.
  const { dir, jobId } = recording({ stage: "queued" });
  // no console entry at all -> 404
  pipelineStatusForRecording(dir);
  await waitFor(() => stageOf(dir) === "error", "the missing job to be reported");
  assert.match(statusOf(dir).message, /no longer exists/);

  const settled = getsFor(jobId);
  await sleep(300);
  assert.equal(getsFor(jobId), settled, "polling must have stopped");
});

test("a console that is merely failing does NOT end the following", async () => {
  // The paired half. A 5xx or a dropped connection says nothing about the
  // job; treating it as fatal would freeze a healthy job on a blip.
  const { dir, jobId } = recording({ stage: "queued" });
  consoleSays(jobId, null, 503);
  pipelineStatusForRecording(dir);
  const first = () => getsFor(jobId);
  await waitFor(() => first() >= 4, "it to keep retrying through the outage");
  assert.equal(stageOf(dir), "queued", "a failing console must not change what the row says");

  consoleSays(jobId, { status: "cancelled", stage: "cancelled", message: "cancelled" });
  await waitFor(() => stageOf(dir) === "cancelled", "it to recover when the console comes back");
});
