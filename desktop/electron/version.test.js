// The update check has one failure mode that matters: telling an operator
// they're up to date when they aren't. Nothing about it looks broken --
// there's no error, no missing screen, just a venue quietly running an old
// build for months. So the comparison is pinned rather than trusted.
import assert from "node:assert/strict";
import { test } from "node:test";
import { compareVersions, updateState } from "./version.js";

test("compares the normal cases", () => {
  assert.equal(compareVersions("1.0.0", "1.0.1"), -1);
  assert.equal(compareVersions("1.0.1", "1.0.0"), 1);
  assert.equal(compareVersions("1.0.0", "1.0.0"), 0);
  assert.equal(compareVersions("1.9.0", "1.10.0"), -1, "10 is newer than 9 -- not a string comparison");
  assert.equal(compareVersions("2.0.0", "1.99.99"), 1);
  assert.equal(compareVersions("1.2.3", "v1.2.3"), 0, "a leading v is the tag's, not the version's");
});

test("a finished release outranks its own prereleases", () => {
  assert.equal(compareVersions("1.0.0-beta.1", "1.0.0"), -1);
  assert.equal(compareVersions("1.0.0", "1.0.0-beta.1"), 1);
  assert.equal(compareVersions("1.0.0-beta.1", "1.0.0-beta.2"), -1);
});

test("unparseable versions return null, never 0", () => {
  // The important half: null must not be confused with "equal", or a
  // malformed version on the server reads as "you're up to date".
  assert.equal(compareVersions("1.0", "1.0.0"), null);
  assert.equal(compareVersions("", "1.0.0"), null);
  assert.equal(compareVersions(undefined, "1.0.0"), null);
  assert.equal(compareVersions("1.0.0", null), null);
  assert.equal(compareVersions("not-a-version", "1.0.0"), null);
});

test("updateState reports outdated only when it actually knows", () => {
  assert.deepEqual(updateState("1.0.0", { version: "1.1.0", url: "https://example.test/r", notes: null }), {
    status: "outdated",
    current: "1.0.0",
    latest: "1.1.0",
    downloadUrl: "https://example.test/r",
    notes: null,
  });
  assert.equal(updateState("1.1.0", { version: "1.1.0", url: "https://example.test/r" }).status, "current");
  // Running something newer than published (a local build) is "current",
  // not "outdated" -- never offer a downgrade.
  assert.equal(updateState("1.2.0", { version: "1.1.0", url: "https://example.test/r" }).status, "current");
});

test("nothing published, or nothing reachable, is 'unknown' -- never 'current'", () => {
  // This is what the console returns when GitHub is unreachable or no
  // desktop release exists yet. Both are true today.
  assert.equal(updateState("1.0.0", { version: null, url: null, notes: null }).status, "unknown");
  assert.equal(updateState("1.0.0", null).status, "unknown");
  assert.equal(updateState("1.0.0", undefined).status, "unknown");
  // A version with no download link is useless -- saying "you're behind"
  // with nowhere to go is worse than saying nothing.
  assert.equal(updateState("1.0.0", { version: "1.1.0", url: null }).status, "unknown");
  // A version we can't parse is also unknown, not current.
  assert.equal(updateState("1.0.0", { version: "garbage", url: "https://example.test/r" }).status, "unknown");
});
