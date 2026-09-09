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
