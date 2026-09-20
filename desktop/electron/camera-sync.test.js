// A camera you add, remove or rename reaches the console now, not at the next
// timer tick.
//
// Reported 2026-09-20 as "if I remove a camera and add one with the same name,
// it shows as calibrated". It never inherited anything -- a re-added camera
// gets a fresh id and the console's row for it started uncalibrated -- but the
// console only learns a camera is gone from the next heartbeat, so for up to a
// full interval the OLD row sat there still listed as calibrated. The data
// showed the cost: a Calibrate was sent to the removed camera's id 36 seconds
// after its replacement was added, and errored.
//
// Real code end to end: the real store, the real cloud.js, and a real local
// HTTP server standing in for the console. Nothing here mocks the thing being
// tested (same reasoning cloud.test.js gives). Own file so it runs in its own
// process and cannot disturb the heartbeat-state tests' module state.
//
// Paired throughout. The tests that a change SYNCS sit beside the cases that
// must NOT: the heartbeat's own writes (a hook there would have each
// heartbeat trigger the next forever) and a burst (which must not become a
// storm of probes).
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test, before, after } from "node:test";
import { FFMPEG } from "./binaries.js";
import { cameraRecordingsDir } from "./capture.js";
import {
  registerAgentOnce, stopHeartbeatLoop, disconnectCloud, requestHeartbeat, HEARTBEAT_DEBOUNCE_MS,
} from "./cloud.js";
import {
  addCameraFromSampleClip, removeCamera, renameCamera, listCameras, setCameraProfile, onCamerasChanged,
} from "./cameras/store.js";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(condition, what, ms = 8000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await condition()) return;
    await sleep(25);
  }
  assert.fail(`timed out waiting for ${what}`);
}

let dir;
let clip;
let server;
let heartbeats; // parsed bodies of every heartbeat POST, in arrival order
let heartbeatDelayMs = 0;
let inFlight = 0;
let maxInFlight = 0;
const createdIds = [];

before(async () => {
  dir = mkdtempSync(path.join(os.tmpdir(), "camera-sync-"));
  clip = path.join(dir, "synthetic.mp4");
  const result = spawnSync(
    FFMPEG,
    ["-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", clip],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 0, `could not build the test clip: ${result.stderr?.slice(-300)}`);

  server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", async () => {
      if (req.url.includes("register")) {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ agentId: "agent-1", apiToken: "tok", brandName: "Test Venue" }));
        return;
      }
      if (req.url.includes("/heartbeat")) {
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        heartbeats.push(JSON.parse(body || "{}"));
        if (heartbeatDelayMs) await sleep(heartbeatDelayMs);
        inFlight -= 1;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ brandName: "Test Venue", cameras: [] }));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  heartbeats = [];
  await registerAgentOnce("access-token", "user-1", `http://127.0.0.1:${server.address().port}`);
  stopHeartbeatLoop(); // registration starts the timer loop; these tests drive heartbeats themselves
  await waitFor(() => heartbeats.length >= 1, "the heartbeat registration fires immediately");
  await sleep(200);
});

after(() => {
  disconnectCloud();
  for (const id of createdIds) rmSync(cameraRecordingsDir({ id }), { recursive: true, force: true });
  rmSync(dir, { recursive: true, force: true });
  server.closeAllConnections();
  server.close();
});

/** Let everything already triggered finish, then forget it -- a clean slate for the next test. */
async function quiesce() {
  await sleep(HEARTBEAT_DEBOUNCE_MS + 300);
  await waitFor(() => inFlight === 0, "in-flight heartbeats to finish");
  heartbeats.length = 0;
}

const addClip = async (label) => {
  const camera = await addCameraFromSampleClip({ label, filePath: clip });
  createdIds.push(camera.id);
  return camera;
};
const reportedIds = (body) => (body.cameras ?? []).map((c) => c.cameraId);

// --- the store tells its listeners about the changes that matter -----------

test("adding, renaming and removing a camera each notify exactly once", async () => {
  let calls = 0;
  const stop = onCamerasChanged(() => { calls += 1; });
  try {
    const camera = await addClip("Listener test");
    assert.equal(calls, 1, "add");
    renameCamera(camera.id, "Listener test renamed");
    assert.equal(calls, 2, "rename");
    removeCamera(camera.id);
    assert.equal(calls, 3, "remove");
  } finally {
    stop();
  }
});

test("the heartbeat's own writes do NOT notify, which would make each heartbeat trigger the next forever", async () => {
  // setCameraProfile is called for every camera on every heartbeat tick. If
  // saving notified, the sync this feature adds would call itself.
  const camera = await addClip("Loop guard");
  let calls = 0;
  const stop = onCamerasChanged(() => { calls += 1; });
  try {
    setCameraProfile(camera.id, { codec: "H264", width: 320, height: 240, fps: 30, bitrateKbps: 100 });
    assert.equal(calls, 0, "a profile refresh is not a change the console needs to hear about now");
    // And the reads must not either.
    listCameras();
    assert.equal(calls, 0);
  } finally {
    stop();
    removeCamera(camera.id);
    await quiesce();
  }
});

test("a listener that throws never fails the operator's own action", async () => {
  // The change is already saved by the time listeners run; a broken one
  // must not turn a successful add into an error dialog.
  const stop = onCamerasChanged(() => { throw new Error("listener blew up"); });
  try {
    const camera = await addClip("Throwing listener");
    assert.ok(camera.id, "the add still succeeded");
    assert.doesNotThrow(() => removeCamera(camera.id));
    assert.ok(!listCameras().some((c) => c.id === camera.id), "and the removal still happened");
  } finally {
    stop();
    await quiesce();
  }
});

// --- and the console hears about it now -----------------------------------

test("removing a camera sends the console a list without it, promptly", async () => {
  // The reported scenario. Before this, the removed camera stayed on the
  // console for up to a full heartbeat interval.
  const camera = await addClip("To be removed");
  await waitFor(() => heartbeats.some((b) => reportedIds(b).includes(camera.id)), "the add to reach the console");
  await quiesce();

  removeCamera(camera.id);
  await waitFor(() => heartbeats.length >= 1, "a heartbeat after the removal");
  assert.ok(!reportedIds(heartbeats.at(-1)).includes(camera.id), "the console must be told the camera is gone");
});

test("removing then re-adding a same-named camera reports the OLD id gone and a NEW id present", async () => {
  const first = await addClip("Court 4");
  await quiesce();
  removeCamera(first.id);
  const second = await addClip("Court 4");
  await waitFor(() => heartbeats.some((b) => reportedIds(b).includes(second.id)), "the replacement to reach the console");

  const last = heartbeats.at(-1);
  assert.ok(!reportedIds(last).includes(first.id), "the removed camera's id must not linger");
  assert.ok(reportedIds(last).includes(second.id));
  assert.notEqual(first.id, second.id, "a re-added camera is a new camera, not the old one");
  removeCamera(second.id);
  await quiesce();
});

test("renaming a camera reaches the console with its new label", async () => {
  const camera = await addClip("Before");
  await quiesce();
  renameCamera(camera.id, "After");
  await waitFor(() => heartbeats.some((b) => (b.cameras ?? []).some((c) => c.cameraId === camera.id && c.label === "After")), "the new label");
  removeCamera(camera.id);
  await quiesce();
});

// --- it must not become a storm ---------------------------------------------

test("a burst of changes collapses into one heartbeat, not one probe of every camera each", async () => {
  // A heartbeat probes EVERY camera before it posts. Four adds in a row
  // triggering four full sweeps would hammer cameras that may allow only
  // one RTSP session.
  await quiesce();
  const made = [];
  for (let i = 0; i < 4; i++) made.push(await addClip(`Burst ${i}`));
  await waitFor(() => heartbeats.length >= 1, "the burst's heartbeat");
  await sleep(HEARTBEAT_DEBOUNCE_MS + 600);
  assert.equal(heartbeats.length, 1, `expected one heartbeat for the whole burst, got ${heartbeats.length}`);
  assert.equal(reportedIds(heartbeats[0]).filter((id) => made.some((c) => c.id === id)).length, 4, "and it carries all four");
  for (const c of made) removeCamera(c.id);
  await quiesce();
});

test("heartbeats never overlap, so an older snapshot cannot land after a newer one", async () => {
  // Two in flight can arrive out of order: an older list still containing a
  // just-removed camera landing AFTER the newer one would put it back.
  //
  // The server holds each heartbeat open for LONGER than the debounce. That
  // is the whole test: an earlier version held it 250ms against a 400ms
  // debounce, so the follow-up request only fired after the first had
  // finished and there was nothing to overlap with -- it passed with the
  // guard removed entirely (found by breaking the guard and watching it
  // stay green).
  heartbeatDelayMs = HEARTBEAT_DEBOUNCE_MS * 3;
  maxInFlight = 0;
  try {
    const a = await addClip("Overlap A");
    await sleep(HEARTBEAT_DEBOUNCE_MS + 50); // its heartbeat has started and is being held open
    assert.equal(inFlight, 1, "precondition: a heartbeat is genuinely in flight");
    removeCamera(a.id); // a change while one is mid-flight; its request fires while that one is still open
    await waitFor(() => heartbeats.length >= 2, "the follow-up heartbeat, so overlap was actually possible", 10_000);
    await waitFor(() => inFlight === 0, "everything to finish", 10_000);
    assert.equal(maxInFlight, 1, `heartbeats overlapped (${maxInFlight} at once)`);
  } finally {
    heartbeatDelayMs = 0;
    await quiesce();
  }
});

test("a change made WHILE a heartbeat is in flight still gets its own heartbeat afterwards", async () => {
  // The paired half of no-overlap. The running heartbeat took its snapshot
  // before the change, so it cannot be trusted to include it. Dropping the
  // request instead of queuing a rerun would leave the console stale for a
  // full interval -- the bug this exists to fix, just narrower.
  // Held open for much longer than the debounce, so the removal's request
  // fires while the first heartbeat is still running -- otherwise it just
  // starts a fresh one and this passes with the rerun logic deleted.
  heartbeatDelayMs = HEARTBEAT_DEBOUNCE_MS * 4;
  try {
    const camera = await addClip("Mid-flight");
    await waitFor(() => heartbeats.length >= 1, "the first heartbeat to start");
    assert.equal(inFlight, 1, "precondition: the first heartbeat is genuinely still in flight");
    removeCamera(camera.id); // arrives while the first is being held open
    await waitFor(() => heartbeats.length >= 2, "a second heartbeat for the change made mid-flight", 12_000);
    assert.ok(!reportedIds(heartbeats.at(-1)).includes(camera.id), "the follow-up must reflect the removal");
  } finally {
    heartbeatDelayMs = 0;
    await quiesce();
  }
});

test("asking for a heartbeat with nothing connected does nothing and does not throw", async () => {
  // Paired with everything above: they prove it fires when connected. A
  // machine that has never signed in must not arm timers or make requests.
  disconnectCloud();
  heartbeats.length = 0;
  assert.doesNotThrow(() => requestHeartbeat());
  await sleep(HEARTBEAT_DEBOUNCE_MS + 300);
  assert.equal(heartbeats.length, 0);
  // Reconnect for any test that follows.
  await registerAgentOnce("access-token", "user-1", `http://127.0.0.1:${server.address().port}`);
  stopHeartbeatLoop();
  await quiesce();
});
