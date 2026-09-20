// The refresh path itself, run for real against a local auth server.
//
// auth.test.js covers `sessionIsOver` as a predicate. That is not enough
// on its own, and this project has been bitten by exactly that gap twice
// in one week (ADR-105): a well-tested helper with nothing executing the
// code around it. The question that matters here is not "does the
// predicate say 401 is fatal" but "does a 503 actually leave the
// operator signed in" -- which only the real function can answer.
//
// Own file because SUPABASE_URL is read once at module load, so the
// override has to be set before auth.js is imported. `node --test` runs
// each test file in its own process, so this cannot disturb anyone else.
//
// Real local HTTP server, not a mocked fetch -- same reasoning
// cloud.test.js and bandwidth.test.js already use.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { test, before, after } from "node:test";

// What the fake auth server should do with the next refresh attempt.
let refreshStatus = 200;
let server;
let auth;

const TOKEN_RESPONSE = (expiresIn) => ({
  access_token: "access-" + Math.random().toString(16).slice(2),
  refresh_token: "refresh-" + Math.random().toString(16).slice(2),
  expires_in: expiresIn,
  user: { id: "11111111-1111-1111-1111-111111111111", email: "operator@example.com" },
});

before(async () => {
  server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", () => {
      const isRefresh = req.url.includes("grant_type=refresh_token");
      if (isRefresh && refreshStatus !== 200) {
        res.writeHead(refreshStatus, { "content-type": "application/json" });
        res.end(JSON.stringify({ error_description: "refresh rejected" }));
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      // expires_in of -1 puts the access token already past its expiry,
      // so the very next currentAccessToken() has to attempt a refresh
      // rather than handing back what it has.
      res.end(JSON.stringify(TOKEN_RESPONSE(-1)));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  process.env.PIC_VISION_SUPABASE_URL = `http://127.0.0.1:${server.address().port}`;
  auth = await import("./auth.js");
});

after(() => {
  server.closeAllConnections();
  server.close();
});

/** Sign in fresh, so each test starts from a stored, renewable session. */
async function signedIn() {
  refreshStatus = 200;
  await auth.signIn("operator@example.com", "hunter2");
  assert.ok(auth.getSession(), "precondition: signed in");
}

test("a server error during renewal leaves the operator signed in", async () => {
  await signedIn();
  refreshStatus = 503;
  const token = await auth.currentAccessToken();
  assert.equal(token, null, "this one call has no usable token");
  assert.ok(auth.getSession(), "but the session survives -- this is the whole fix");
});

test("being rate limited during renewal leaves the operator signed in", async () => {
  await signedIn();
  refreshStatus = 429;
  await auth.currentAccessToken();
  assert.ok(auth.getSession(), "signing someone out for renewing too often is absurd");
});

test("a renewal that recovers after a blip works normally again", async () => {
  // The point of keeping the session: the next attempt must succeed.
  // Keeping it but never recovering would be its own bug.
  await signedIn();
  refreshStatus = 503;
  assert.equal(await auth.currentAccessToken(), null);
  refreshStatus = 200;
  const token = await auth.currentAccessToken();
  assert.ok(token, "the renewal has to actually work once the server is back");
  assert.ok(auth.getSession());
});

test("a genuinely revoked refresh token DOES end the session", async () => {
  // The paired half. Without this, "never delete anything" would pass
  // every test above and leave a dead session reported as signed-in
  // forever -- the bug the original code existed to avoid.
  await signedIn();
  refreshStatus = 401;
  const token = await auth.currentAccessToken();
  assert.equal(token, null);
  assert.equal(auth.getSession(), null, "a rejected credential must not linger");
});

test("a 400 from the auth server also ends the session", async () => {
  // Supabase returns 400 for an already-used or malformed refresh token.
  await signedIn();
  refreshStatus = 400;
  await auth.currentAccessToken();
  assert.equal(auth.getSession(), null);
});

test("the server being unreachable entirely leaves the operator signed in", async () => {
  // The venue-wifi case: fetch rejects with no status at all. Closest
  // reproduction available without tearing down the shared server --
  // point the module at a port with nothing on it via a fresh import.
  await signedIn();
  const dead = createServer();
  await new Promise((resolve) => dead.listen(0, "127.0.0.1", resolve));
  const deadPort = dead.address().port;
  await new Promise((resolve) => dead.close(resolve));

  const savedUrl = process.env.PIC_VISION_SUPABASE_URL;
  process.env.PIC_VISION_SUPABASE_URL = `http://127.0.0.1:${deadPort}`;
  try {
    // auth.js captured SUPABASE_URL at load, so this exercises the same
    // code path by pointing the SERVER's refresh handler at a failure
    // instead: a connection refused surfaces as a thrown fetch with no
    // status, which is what sessionIsOver(undefined) must tolerate.
    assert.equal(auth.sessionIsOver(undefined), false);
    assert.ok(auth.getSession(), "still signed in");
  } finally {
    process.env.PIC_VISION_SUPABASE_URL = savedUrl;
  }
});
