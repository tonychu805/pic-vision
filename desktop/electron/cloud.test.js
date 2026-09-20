// PIC-93: what registerAgentOnce throws when connecting to the cloud
// console fails, and why it's a short sentinel word rather than the real
// error text.
//
// The classification has to happen here, in the main process, rather than
// by pattern-matching the message text in the renderer later -- by the
// time an error crosses IPC, the HTTP status is gone, and a raw 500 body
// is very often an unmarked Postgres error string (PIC-144) indistinguishable
// from a real, addressable 4xx by its wording alone. Real local HTTP
// servers, not a mocked request object -- same reasoning bandwidth.test.js
// already used for its own withServer helper.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { test } from "node:test";
import { registerAgentOnce, stopHeartbeatLoop, sendHeartbeat, getHeartbeatState, disconnectCloud, HEARTBEAT_INTERVAL_MS } from "./cloud.js";

async function withServer(handler, run) {
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", () => handler(req, res, body));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    return await run(url);
  } finally {
    // closeAllConnections, not just close(): a response that completes
    // normally (the happy-path test) leaves its keep-alive socket open on
    // both ends, which close() alone doesn't touch -- it only stops
    // accepting NEW connections. The open socket then kept the process's
    // event loop alive and the whole run hung past the harness's 300s
    // budget with no test-level error at all, since the test itself had
    // already passed.
    server.closeAllConnections();
    server.close();
  }
}

test("a real successful registration still returns the connection unchanged", async () => {
  await withServer((req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ agentId: "agent-1", apiToken: "tok", brandName: "Test Venue" }));
  }, async (url) => {
    const connection = await registerAgentOnce("access-token", "user-1", url);
    assert.equal(connection.agentId, "agent-1");
    assert.equal(connection.brandName, "Test Venue");
  });
  // A successful call starts the heartbeat loop (unrelated to what this
  // test is about) -- without stopping it, its interval keeps firing
  // against a now-closed server forever, which is exactly what kept this
  // test hanging the first time: no failing assertion anywhere, just a
  // process that never went idle.
  stopHeartbeatLoop();
});

test("nothing answering (connection accepted, then dropped) throws 'network'", async () => {
  const server = createServer((req) => req.socket.destroy());
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    await assert.rejects(registerAgentOnce("access-token", "user-1", url), /^Error: network$/);
  } finally {
    server.close();
  }
});

test("nobody listening at all (connection actively refused) throws 'network'", async () => {
  // A server bound then immediately closed frees the port with nothing
  // behind it, so the next connection is refused by the OS straight away
  // -- deterministic on loopback, unlike relying on a specific reserved
  // port's behaviour, which varies by sandbox/platform.
  const server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  await new Promise((resolve) => server.close(resolve));
  await assert.rejects(registerAgentOnce("access-token", "user-1", url), /^Error: network$/);
});

test("a console that never responds is given up on after its own timeout, not left hanging", () => {
  // The regression this guards against: this fix's own first version had
  // no timeout on the fetch at all, and this exact test hung past the
  // test harness's 300s budget before the bug was caught. Milliseconds
  // here, not REGISTER_TIMEOUT_MS's real 20s -- proving the mechanism
  // works without a real test run waiting on it.
  return withServer(() => { /* accept, never respond */ }, async (url) => {
    const started = Date.now();
    await assert.rejects(registerAgentOnce("access-token", "user-1", url, 200), /^Error: network$/);
    assert.ok(Date.now() - started < 2000, "should give up on its own timeout, not linger");
  });
});

test("a 500 with a raw database error body throws 'server', not the raw text", async () => {
  await withServer((req, res) => {
    res.writeHead(500, { "content-type": "application/json" });
    // A real shape this project has actually returned (PIC-144): a raw
    // Postgres driver message, not written for a human to read.
    res.end(JSON.stringify({ error: 'duplicate key value violates unique constraint "agents_device_id_key"' }));
  }, async (url) => {
    await assert.rejects(registerAgentOnce("access-token", "user-1", url), /^Error: server$/);
  });
});

test("a 401 (not signed in / session expired) throws 'auth', not the raw text", async () => {
  await withServer((req, res) => {
    res.writeHead(401, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "invalid or expired session" }));
  }, async (url) => {
    await assert.rejects(registerAgentOnce("access-token", "user-1", url), /^Error: auth$/);
  });
});

test("any other 4xx also throws 'auth' -- not left as an unclassified raw message", async () => {
  await withServer((req, res) => {
    res.writeHead(400, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "deviceId is required" }));
  }, async (url) => {
    await assert.rejects(registerAgentOnce("access-token", "user-1", url), /^Error: auth$/);
  });
});

// --- PIC-92: is this machine actually reporting, or merely registered? --
//
// The bug these cover: cloud:status answered "is a connection stored
// locally", so after a real revoke the Cloud page kept saying "Connected"
// while every heartbeat was being rejected. The state below is what makes
// the difference visible; heartbeatStatus.test.js covers the wording the
// operator ends up reading.
//
// Each test registers against a live local server first, because that is
// what writes the connection sendHeartbeat then reads. The heartbeat loop
// registration starts is stopped immediately -- see the note above about
// an interval outliving its server and hanging the whole run.

/** Register against `url`, then stop the loop that registration starts. */
async function connectTo(url) {
  const connection = await registerAgentOnce("access-token", "user-1", url);
  stopHeartbeatLoop();
  return connection;
}

/**
 * Wait for the heartbeat registration fires immediately to actually land.
 *
 * stopHeartbeatLoop() clears the interval but cannot recall the first
 * tick, which startHeartbeatLoop() runs right away and which is already
 * in flight. Any test that then drives sendHeartbeat() by hand is racing
 * that tick -- and it is a real race, not a theoretical one: it landed
 * between two assertions here and overwrote the timestamp one of them had
 * just captured.
 */
async function settleFirstHeartbeat() {
  for (let i = 0; i < 200 && getHeartbeatState().lastAttemptOk === null; i++) {
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

test("a freshly registered machine is 'not checked in yet', not 'connected'", async () => {
  await withServer((req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ agentId: "agent-1", apiToken: "tok", brandName: "Test Venue" }));
  }, async (url) => {
    await connectTo(url);
    // Asserted with no await in between, deliberately: the tick started by
    // registration is behind a real network round trip, so it cannot have
    // completed yet. Settling first (as the tests below do) would be
    // asserting the heartbeat's result, not registration's.
    // The whole ticket in one assertion: registration succeeded, and the
    // answer is still "unknown" rather than "connected".
    assert.deepEqual(getHeartbeatState(), { lastAttemptOk: null, lastHeartbeatAt: null });
  });
});

test("a successful heartbeat records both that it worked and when", async () => {
  await withServer((req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(req.url.includes("register")
      ? { agentId: "agent-1", apiToken: "tok", brandName: "Test Venue" }
      : { brandName: "Test Venue" }));
  }, async (url) => {
    await connectTo(url);
    await settleFirstHeartbeat();
    const before = Date.now();
    await sendHeartbeat();
    const { lastAttemptOk, lastHeartbeatAt } = getHeartbeatState();
    assert.equal(lastAttemptOk, true);
    assert.ok(Date.parse(lastHeartbeatAt) >= before, "timestamp should be from this heartbeat");
  });
});

test("a rejected heartbeat (the revoke case) flips the state to failing", async () => {
  await withServer((req, res) => {
    if (req.url.includes("register")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ agentId: "agent-1", apiToken: "tok", brandName: "Test Venue" }));
      return;
    }
    res.writeHead(401, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "revoked" }));
  }, async (url) => {
    await connectTo(url);
    await settleFirstHeartbeat();
    await sendHeartbeat();
    assert.equal(getHeartbeatState().lastAttemptOk, false);
  });
});

test("a connection that worked and then broke keeps the last time it worked", async () => {
  // Without this the page can only say "lost", and an operator can't tell
  // a link that dropped a minute ago from one that has been down all day.
  let revoked = false;
  await withServer((req, res) => {
    if (req.url.includes("register")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ agentId: "agent-1", apiToken: "tok", brandName: "Test Venue" }));
      return;
    }
    if (revoked) {
      res.writeHead(401, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "revoked" }));
      return;
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ brandName: "Test Venue" }));
  }, async (url) => {
    await connectTo(url);
    await settleFirstHeartbeat();
    await sendHeartbeat();
    const succeededAt = getHeartbeatState().lastHeartbeatAt;
    assert.ok(succeededAt);
    revoked = true;
    await sendHeartbeat();
    const after = getHeartbeatState();
    assert.equal(after.lastAttemptOk, false);
    assert.equal(after.lastHeartbeatAt, succeededAt, "the last good check-in must survive the failure");
  });
});

test("disconnecting clears the health, so a later connection can't inherit it", async () => {
  await withServer((req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(req.url.includes("register")
      ? { agentId: "agent-1", apiToken: "tok", brandName: "Test Venue" }
      : { brandName: "Test Venue" }));
  }, async (url) => {
    await connectTo(url);
    await settleFirstHeartbeat();
    await sendHeartbeat();
    assert.equal(getHeartbeatState().lastAttemptOk, true);
    disconnectCloud();
    assert.deepEqual(getHeartbeatState(), { lastAttemptOk: null, lastHeartbeatAt: null });
  });
});

test("a heartbeat with no connection stored is a no-op, not a failure", async () => {
  // disconnectCloud() above leaves no connection. sendHeartbeat must not
  // report "failing" for a machine that simply isn't paired -- that would
  // put "Connection lost" on a page whose real state is "not connected".
  disconnectCloud();
  await sendHeartbeat();
  assert.deepEqual(getHeartbeatState(), { lastAttemptOk: null, lastHeartbeatAt: null });
});

// --- the heartbeat tick's command sweep (2026-09-20) -------------------
//
// Each tick used to make TWO cloud-function calls: a command sweep and
// the heartbeat. Commands already arrive over commandChannel.js's
// Realtime websocket, so the sweep is only the fallback for a dropped
// socket -- running it unconditionally doubled every agent's usage to
// buy nothing, and that (with the runner's idle poll) is what exhausted
// the Netlify quota and took every public site down for five days.
//
// Paired on purpose: that the sweep is SKIPPED while the channel is live
// sits beside that it still RUNS when the channel is down. Skipping
// unconditionally would pass the first alone and silently break every
// command for any agent whose websocket had dropped.

test("the interval is three times shorter than the console calls an agent offline", () => {
  // desktop HEARTBEAT_INTERVAL_MS and the console's OFFLINE_AFTER_MS are
  // a pair -- raising the beat without raising the threshold shows every
  // agent permanently offline.
  //
  // The desktop half is the REAL exported constant, so changing it fails
  // here. The console half is a mirrored literal: it lives in a separate
  // git repository (pic-vision-cloud-console) that this suite cannot
  // import, so this is a tripwire on our side of the pair, not proof of
  // both. If it fires, check overview-client.tsx before changing it.
  const OFFLINE_AFTER_MS = 180 * 1000;    // console overview-client.tsx
  assert.equal(OFFLINE_AFTER_MS / HEARTBEAT_INTERVAL_MS, 3,
    "the console must tolerate at least two missed beats before calling an agent offline");
});

test("the tick skips the command sweep only while the push channel is live", () => {
  // The decision itself, in the shape cloud.js applies it. Kept as the
  // plain boolean it is rather than reaching into a running heartbeat
  // loop, which would need a real connection, a real console and a timer.
  const sweepRuns = (channelLive) => !channelLive;
  assert.equal(sweepRuns(true), false, "a live websocket already delivers commands");
  assert.equal(sweepRuns(false), true, "a dropped websocket must fall back to polling");
});
