// Who is this device registered AS?
//
// Reported 2026-09-09: signed in on a Mac as one account, and the app said
// "Connected as <a brand belonging to a different account>" -- and would
// have filed every camera, job and reel under that other brand, because
// the stored connection carries the agent token, not the session.
// Sign-out only cleared the session; sign-in only registered when there
// was no connection at all, so the old account's agent identity survived
// the account change (ADR-094).
//
// These are paired deliberately. One test proves a mismatch is noticed.
// One proves the same account is left alone -- the original condition
// existed to avoid minting an agent row and rotating a token on every
// ordinary re-login, and a fix that lost that would be its own bug. And
// one proves a mismatch is never resolved *silently*: moving a machine
// hands its cameras to another venue, so it has to be asked, not assumed.
import assert from "node:assert/strict";
import { test } from "node:test";
import { registrationState, sessionIsOver } from "./auth.js";

const ACCOUNT_A = "1cbc3fd0-0000-0000-0000-00000000000a";
const ACCOUNT_B = "9de41aa2-0000-0000-0000-00000000000b";
const BRAND_A = "Pickle Day Social Club";
const BRAND_B = "Syno Pickleball";

test("a device with no connection registers itself, no questions", () => {
  assert.equal(registrationState(null, ACCOUNT_A, BRAND_A), "none");
  assert.equal(registrationState(undefined, ACCOUNT_A, BRAND_A), "none");
});

test("a device already registered as this account is left alone", () => {
  const connection = { agentId: "agent-1", brandName: BRAND_A, userId: ACCOUNT_A };
  assert.equal(
    registrationState(connection, ACCOUNT_A, BRAND_A),
    "ok",
    "ordinary re-login must not mint a new agent row or rotate the token",
  );
});

test("a device registered as somebody else asks, and never moves on its own", () => {
  // The reported bug, and the reason this isn't just auto-corrected:
  // moving the machine takes its cameras to another venue.
  const connection = { agentId: "agent-1", brandName: BRAND_B, userId: ACCOUNT_B };
  assert.equal(registrationState(connection, ACCOUNT_A, BRAND_A), "mismatch");
});

test("an old connection on the same brand is adopted, not interrogated", () => {
  // Every build before 2026-09-09 wrote a connection with no owner on it.
  // If the brand still matches, nothing changed hands -- the record was
  // just missing a field, and upgrading shouldn't raise a dialog for
  // every existing user.
  const legacy = { agentId: "agent-1", brandName: BRAND_A };
  assert.equal(registrationState(legacy, ACCOUNT_A, BRAND_A), "adopt");
});

test("an old connection on a different brand still asks", () => {
  // This is the state the reported Mac is actually in: registered before
  // userId existed, and to the wrong venue. Missing field or not, this
  // one is a real mismatch and must not be adopted.
  const legacy = { agentId: "agent-1", brandName: BRAND_B };
  assert.equal(registrationState(legacy, ACCOUNT_A, BRAND_A), "mismatch");
});

test("an unknown brand is treated as a mismatch, not adopted", () => {
  // If the brand lookup failed, we don't know whether anything changed
  // hands -- so ask, rather than assume the safe-looking answer.
  const legacy = { agentId: "agent-1", brandName: BRAND_A };
  assert.equal(registrationState(legacy, ACCOUNT_A, undefined), "mismatch");
});

// --- what counts as proof a session is over (2026-09-20) --------------
//
// Reported as "the remember credential box doesn't work". The box was
// decoration, but the complaint underneath was real: the app kept asking
// for a password. Any failure of the hourly token renewal deleted the
// stored login outright -- a 5xx, a rate limit, a venue's wifi dropping
// mid-renewal, all treated as "your credential is dead".
//
// Paired on purpose. The tests that a blip must NOT sign you out sit
// beside the test that a genuinely revoked token still MUST, because
// "never delete anything" would pass the first group on its own and
// leave a dead session reported as signed-in forever -- which is the bug
// the original code was written to avoid.

test("a revoked or expired refresh token really does end the session", () => {
  // What Supabase returns for a refresh token that is revoked, expired,
  // or already used. This half must keep working.
  assert.equal(sessionIsOver(400), true);
  assert.equal(sessionIsOver(401), true);
});

test("a server problem does not end the session", () => {
  for (const status of [500, 502, 503, 504]) {
    assert.equal(sessionIsOver(status), false, `HTTP ${status} is our problem, not the credential's`);
  }
});

test("being rate limited does not end the session", () => {
  // Signing someone out for renewing too often is the worst possible
  // response to being told to slow down.
  assert.equal(sessionIsOver(429), false);
});

test("a network failure, which carries no status at all, does not end the session", () => {
  // `fetch` rejects with a TypeError and no status when DNS fails or the
  // connection drops -- the venue-wifi case, and the most common one.
  assert.equal(sessionIsOver(undefined), false);
  assert.equal(sessionIsOver(null), false);
  assert.equal(sessionIsOver(NaN), false);
});

test("an unexpected status is treated as not-proof", () => {
  // Anything the auth server has not told us means "revoked" is not a
  // reason to destroy a working login. Unknown fails safe.
  for (const status of [0, 301, 404, 418, 451, 999]) {
    assert.equal(sessionIsOver(status), false, `HTTP ${status} is not proof of revocation`);
  }
});
