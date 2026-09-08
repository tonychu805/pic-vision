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
import { registrationState } from "./auth.js";

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
