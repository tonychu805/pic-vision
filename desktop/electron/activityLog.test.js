import test from "node:test";
import assert from "node:assert/strict";
import { logEvent, msg, getEvents, clearEvents } from "./activityLog.js";

test("a message is stored as English text plus its key and values", () => {
  clearEvents();
  logEvent("signed_in", msg("log.signedIn", { email: "a@b.c" }), msg("log.noRalliesDetail"));
  const [e] = getEvents();
  assert.equal(e.title, "Signed in as a@b.c");
  assert.equal(e.titleKey, "log.signedIn");
  assert.deepEqual(e.titleVars, { email: "a@b.c" });
  assert.equal(e.detailKey, "log.noRalliesDetail");
  clearEvents();
});

test("plain strings (raw errors, paths) are stored as written, with no key", () => {
  clearEvents();
  logEvent("pipeline_failed", msg("log.uploadFailed", { label: "Court 1" }), "HTTP 403: expired");
  const [e] = getEvents();
  assert.equal(e.detail, "HTTP 403: expired");
  assert.equal(e.detailKey, undefined);
  clearEvents();
});
