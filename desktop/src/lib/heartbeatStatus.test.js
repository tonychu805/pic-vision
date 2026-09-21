// PIC-92. The assertion that matters in every one of these is which words
// the operator sees, not which branch ran: "Connected" must appear only
// when a heartbeat has actually succeeded most recently, and must not
// appear when it hasn't.
import assert from "node:assert/strict";
import { test } from "node:test";
import { heartbeatStatus, timeAgo } from "./heartbeatStatus.js";

const NOW = Date.parse("2026-09-20T12:00:00.000Z");
const ago = (ms) => new Date(NOW - ms).toISOString();

test("the page's own two layouts are left alone", () => {
  // undefined = the first read is still in flight, null = not registered.
  assert.equal(heartbeatStatus(undefined, NOW), null);
  assert.equal(heartbeatStatus(null, NOW), null);
});

test("a registered machine that has not checked in yet does not claim to be connected", () => {
  const status = heartbeatStatus({ brandName: "Riverside Courts", lastAttemptOk: null, lastHeartbeatAt: null }, NOW);
  assert.equal(status.tone, "pending");
  assert.match(status.title, /Connecting to Riverside Courts/);
  assert.doesNotMatch(status.title, /^Connected/);
});

test("a succeeding heartbeat says Connected, with when it last checked in", () => {
  const status = heartbeatStatus(
    { brandName: "Riverside Courts", lastAttemptOk: true, lastHeartbeatAt: ago(20_000) },
    NOW,
  );
  assert.equal(status.tone, "ok");
  assert.equal(status.title, "Connected to Riverside Courts");
  assert.equal(status.detail, "Last check-in just now.");
});

test("a failing heartbeat says the connection is lost, and how long it has been", () => {
  // This is the revoke case from the ticket: the connection is still
  // stored, so the old code said "Connected to Riverside Courts".
  const status = heartbeatStatus(
    { brandName: "Riverside Courts", lastAttemptOk: false, lastHeartbeatAt: ago(3 * 60_000) },
    NOW,
  );
  assert.equal(status.tone, "lost");
  assert.equal(status.title, "Connection lost");
  assert.match(status.detail, /Last successful check-in 3 minutes ago/);
  assert.doesNotMatch(status.title, /Connected/);
});

test("never having checked in is told apart from having lost a working link", () => {
  const never = heartbeatStatus({ brandName: "Riverside Courts", lastAttemptOk: false, lastHeartbeatAt: null }, NOW);
  assert.match(never.detail, /has not checked in to Riverside Courts successfully yet/);
  assert.doesNotMatch(never.detail, /Last successful check-in/);
});

test("a failure points at the Log tab, which is where the reason actually is", () => {
  // Deliberately not the error text itself -- PIC-93/PIC-144. The page
  // gets state; the reason stays in the log.
  for (const lastHeartbeatAt of [null, ago(60 * 60_000)]) {
    const status = heartbeatStatus({ brandName: "V", lastAttemptOk: false, lastHeartbeatAt }, NOW);
    assert.match(status.detail, /Log tab/);
  }
});

test("timeAgo is coarse, and plural-correct at the boundaries", () => {
  assert.equal(timeAgo(ago(0), NOW), "just now");
  assert.equal(timeAgo(ago(59_000), NOW), "just now");
  assert.equal(timeAgo(ago(60_000), NOW), "1 minute ago");
  assert.equal(timeAgo(ago(2 * 60_000), NOW), "2 minutes ago");
  assert.equal(timeAgo(ago(60 * 60_000), NOW), "1 hour ago");
  assert.equal(timeAgo(ago(5 * 60 * 60_000), NOW), "5 hours ago");
  assert.equal(timeAgo(ago(24 * 60 * 60_000), NOW), "1 day ago");
  assert.equal(timeAgo(ago(3 * 24 * 60 * 60_000), NOW), "3 days ago");
});

test("a clock behind the console's reads as just now, not as a negative age", () => {
  const future = new Date(NOW + 5 * 60_000).toISOString();
  assert.equal(timeAgo(future, NOW), "just now");
});

test("an unparseable timestamp degrades to no detail rather than to 'NaN ago'", () => {
  assert.equal(timeAgo("not a date", NOW), null);
  const status = heartbeatStatus({ brandName: "V", lastAttemptOk: true, lastHeartbeatAt: "not a date" }, NOW);
  assert.equal(status.title, "Connected to V");
  assert.doesNotMatch(status.detail, /NaN/);
});

// 2026-09-21: the heartbeat stuck waiting on a call that never returned. No
// attempt *failed*, so lastAttemptOk stayed true from the last success and the
// page said Connected for as long as the machine stayed silent. Paired: a
// recent success must still read Connected, or this would just be a machine
// that always claims to be broken.
test("a heartbeat that stopped arriving without failing does not say Connected", () => {
  const status = heartbeatStatus(
    { brandName: "Riverside Courts", lastAttemptOk: true, lastHeartbeatAt: ago(11 * 60_000) },
    NOW,
  );
  assert.equal(status.tone, "lost");
  assert.doesNotMatch(status.title, /^Connected/);
  assert.match(status.title, /Not checking in to Riverside Courts/);
  assert.match(status.detail, /11 minutes ago/);
});

test("a check-in within the last few beats still says Connected", () => {
  for (const ms of [0, 20_000, 60_000, 2 * 60_000 + 30_000]) {
    const status = heartbeatStatus({ brandName: "V", lastAttemptOk: true, lastHeartbeatAt: ago(ms) }, NOW);
    assert.equal(status.tone, "ok", `${ms}ms since the last check-in should still be fine`);
    assert.match(status.title, /^Connected to V/);
  }
});
