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
import { registerAgentOnce, stopHeartbeatLoop } from "./cloud.js";

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
