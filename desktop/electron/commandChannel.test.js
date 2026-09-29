// The channel is mostly a websocket, which a unit test can't usefully
// stand in for -- it was verified against the real Supabase project
// instead (a real INSERT arrived in 638ms, versus the 28.7s and 31.4s
// measured on the poll). What IS worth pinning here is the part that
// decides whether to start at all, because every one of those guards is a
// case where the app must fall back to polling rather than break: an
// agent that never registered, an operator who signed out, a token that
// wouldn't refresh.
import assert from "node:assert/strict";
import { test } from "node:test";
import { isCommandChannelLive, startCommandChannel, stopCommandChannel } from "./commandChannel.js";

const CONFIG = { url: "https://example.supabase.co", anonKey: "anon", onCommand: () => {} };

test("nothing is live before anything starts", () => {
  assert.equal(isCommandChannelLive(), false);
});

test("an unregistered machine doesn't subscribe", async () => {
  const started = await startCommandChannel({ ...CONFIG, agentId: null, getAccessToken: async () => "token" });
  assert.equal(started, false, "no agent id means there is nothing to filter on");
  assert.equal(isCommandChannelLive(), false);
});

test("a signed-out machine doesn't subscribe, and doesn't throw", async () => {
  // This is the ordinary state of a venue machine whose operator signed
  // out: it must keep obeying commands via the 30s poll, so this path has
  // to be a quiet `false`, not an error that takes the startup path down.
  const started = await startCommandChannel({ ...CONFIG, agentId: "agent-1", getAccessToken: async () => null });
  assert.equal(started, false);
  assert.equal(isCommandChannelLive(), false);
});

test("a token that fails to refresh is the caller's problem, not a crash", async () => {
  await assert.rejects(
    () => startCommandChannel({ ...CONFIG, agentId: "agent-1", getAccessToken: async () => { throw new Error("refresh failed"); } }),
    /refresh failed/,
    "main.js catches this and logs 'polling only'",
  );
  assert.equal(isCommandChannelLive(), false);
});

test("stopping when nothing was started is safe", async () => {
  await stopCommandChannel();
  await stopCommandChannel();
  assert.equal(isCommandChannelLive(), false);
});

// Wiring, checked in main.js's source because main.js can't be imported
// outside Electron (same approach as ipc-contract.test.js). The channel
// authenticates with the session and filters on the agent id, so every
// handler that changes either must rebind it. Sign-in was missing until
// 2026-09-29: a fresh install registers inside signIn(), so its first
// Calibrate waited on the 60s poll until the app was restarted. The
// "no token -> nothing starts" half of sign-out is pinned above.
test("every handler that changes the session or the registration rebinds the channel", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const body = (channel) => {
    const start = source.indexOf(`ipcMain.handle("${channel}"`);
    assert.notEqual(start, -1, `${channel} no longer exists in main.js`);
    const next = source.indexOf("ipcMain.handle(", start + 1);
    return source.slice(start, next === -1 ? undefined : next);
  };
  for (const channel of ["auth:signIn", "auth:signOut", "cloud:register"]) {
    assert.match(body(channel), /syncCommandChannel\(\)/, `${channel} must call syncCommandChannel()`);
  }
  assert.match(body("cloud:disconnect"), /stopCommandChannel\(\)/, "cloud:disconnect must stop the channel");
});
