// PIC-146: encryptField()'s fallback when the OS vault is unavailable
// stays the same (return the plaintext value) -- what changed is that it
// now says so, once per launch, instead of silently.
//
// The electron-store stub's safeStorage always reports
// isEncryptionAvailable() === false (electron-stub-loader.mjs), which
// happens to be exactly the case this file needs to exercise -- no extra
// mocking required to reach the fallback path.
//
// Test order matters within this file: warnedThisLaunch is module-level
// state, matching how this actually runs (once per app launch, not once
// per call), so the "warns exactly once" test has to be the very first
// call to encryptField in the whole file -- everything after it runs with
// the flag already tripped, which is fine, since every other test here is
// checking the return value, not the logging.
import assert from "node:assert/strict";
import { test } from "node:test";
import { decryptField, encryptField, isEncrypted, PREFIX } from "./secureField.js";
import { getEvents } from "./activityLog.js";

test("the first call while unavailable warns exactly once", () => {
  const before = getEvents().length;
  encryptField("first-secret-this-file-encrypts");
  const events = getEvents();
  assert.equal(events.length, before + 1, "exactly one new log entry");
  assert.equal(events[0].type, "secure_storage_unavailable");
  assert.match(events[0].title, /not encrypted/);
});

test("every later call while still unavailable does not warn again", () => {
  const before = getEvents().length;
  encryptField("second-secret");
  encryptField("third-secret");
  encryptField("fourth-secret");
  assert.equal(getEvents().length, before, "no new log entries -- would flood the Log tab on an affected machine otherwise");
});

test("the fallback still returns the plaintext value unchanged", () => {
  assert.equal(encryptField("hunter2"), "hunter2");
});

test("null and undefined pass through without throwing", () => {
  assert.equal(encryptField(null), null);
  assert.equal(encryptField(undefined), undefined);
});

test("isEncrypted only recognizes this module's own prefix", () => {
  assert.equal(isEncrypted(PREFIX + "abc"), true);
  assert.equal(isEncrypted("plain text"), false);
  assert.equal(isEncrypted(123), false);
  assert.equal(isEncrypted(null), false);
});

test("decryptField passes through anything without the prefix unchanged", () => {
  // Covers both real cases that collapse into this branch: a legacy
  // plaintext value written before encryption shipped, and (under this
  // test's stubbed vault) the plaintext the fallback above just returned.
  assert.equal(decryptField("plain text"), "plain text");
  assert.equal(decryptField(42), 42);
});

// Not tested here: a corrupted or foreign-vault-encrypted value decrypting
// to null via the try/catch in decryptField. The stub's fake
// decryptString ((b) => b.toString()) never actually throws the way real
// safeStorage does on a key it can't open, so this harness has no way to
// reach that branch honestly -- asserting against it here would test the
// stub's leniency, not the real behavior. Unchanged code, not part of
// this fix; left to a real Electron run to exercise for real.
