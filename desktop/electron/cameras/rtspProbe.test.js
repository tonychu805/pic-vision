// The timeout has to cover the CONNECT phase, not just an in-flight request.
//
// Found by UAT on 2026-09-18: typing an address with no camera on it left
// "Add a camera" on "Looking for a video stream…" -- a step with no Cancel
// button -- for about 15 minutes. openRtspConnection() set a 2.5s socket
// timeout and listened for it, but the listener only settled an in-flight
// request, and during connect there isn't one. So the wait fell through to
// the OS's own connect timeout (134s measured on this Linux box), once per
// entry in findWorkingRtspPath's seven-path ladder.
import assert from "node:assert/strict";
import net from "node:net";
import { test } from "node:test";
import { describeRtspStream } from "./rtspProbe.js";

// Starts a server on a free port, hands back its port and a close().
// close() drops the server's own accepted sockets first: server.close()
// alone waits on every live connection, which never finishes when the test
// is precisely about a connection nobody is answering on.
function startServer(onConnection) {
  return new Promise((resolve) => {
    const sockets = new Set();
    const server = net.createServer((socket) => {
      sockets.add(socket);
      socket.on("close", () => sockets.delete(socket));
      onConnection(socket);
    });
    server.listen(0, "127.0.0.1", () => {
      resolve({
        port: server.address().port,
        close: () => new Promise((r) => {
          for (const socket of sockets) socket.destroy();
          server.close(r);
        }),
      });
    });
  });
}

test("a server that answers is still confirmed (the fix didn't break the happy path)", async () => {
  const server = await startServer((socket) => {
    socket.on("data", () => socket.write("RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n"));
  });
  try {
    const { url } = await describeRtspStream({
      hostname: "127.0.0.1", port: server.port, path: "/1",
      username: "u", password: "p", timeoutMs: 2000,
    });
    assert.equal(url, `rtsp://127.0.0.1:${server.port}/1`);
  } finally {
    await server.close();
  }
});

test("a server that accepts and then goes silent times out, and says so", async () => {
  // The case the old listener did handle: connected, request written, no
  // reply. Kept as a test so the rewrite can't lose it.
  const server = await startServer(() => { /* accept, never answer */ });
  try {
    const started = Date.now();
    await assert.rejects(
      describeRtspStream({
        hostname: "127.0.0.1", port: server.port, path: "/1",
        username: "u", password: "p", timeoutMs: 250,
      }),
      /Timed out/,
    );
    assert.ok(Date.now() - started < 3000, "should give up on its own timeout, not linger");
  } finally {
    await server.close();
  }
});

test("an address that never completes a connection gives up on timeoutMs, not the OS's timeout", async () => {
  // 192.0.2.1 is TEST-NET-1 (RFC 5737): reserved for documentation, so
  // nothing routes to it and the connect attempt hangs rather than being
  // refused. That hang is the actual regression -- 134s per attempt.
  //
  // A network that answers unreachable immediately (some CI sandboxes)
  // makes this pass for a different reason, which is fine: the assertion is
  // "gives up quickly", and quickly is what matters to the operator. The
  // budget is deliberately far below any OS connect timeout (Linux ~134s,
  // macOS ~75s) so it can only pass if something here gave up first.
  const started = Date.now();
  await assert.rejects(describeRtspStream({
    hostname: "192.0.2.1", port: 554, path: "/1",
    username: "u", password: "p", timeoutMs: 300,
  }));
  const elapsed = Date.now() - started;
  assert.ok(elapsed < 5000, `gave up after ${elapsed}ms, expected well under the OS connect timeout`);
});
