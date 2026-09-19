// The crash reporter, exercised rather than admired.
//
// ADR-105's lesson, applied to the module written because of it: the bug
// that shipped in 1.5.0 lived in a function no test ever executed, next
// to nine passing tests of the pure helper beside it. So these run
// installCrashReporting for real -- against a stand-in process and app,
// and a real temp directory -- and then fire the events, rather than only
// checking the wording helper.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { EventEmitter } from "node:events";
import { describeExit, installCrashReporting, CRASH_LOG } from "./crashReport.js";

function harness() {
  const dir = mkdtempSync(path.join(os.tmpdir(), "crashreport-"));
  const logged = [];
  const proc = new EventEmitter();
  const app = new EventEmitter();
  installCrashReporting({
    proc,
    app,
    logEvent: (type, title, detail) => logged.push({ type, title, detail }),
    userDataDir: dir,
    now: () => "2026-09-20T00:00:00.000Z",
  });
  return {
    dir, logged, proc, app,
    crashLog: () => (existsSync(path.join(dir, CRASH_LOG)) ? readFileSync(path.join(dir, CRASH_LOG), "utf8") : ""),
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  };
}

test("an unhandled rejection is recorded instead of taking the app down", () => {
  // The shape the operator actually hit: no dialog, no message, the app
  // simply gone. Node 22 throws on an unhandled rejection unless someone
  // is listening, so the listener existing IS the fix.
  const h = harness();
  try {
    assert.equal(h.proc.listenerCount("unhandledRejection"), 1, "nothing is listening for unhandled rejections");
    h.proc.emit("unhandledRejection", new Error("the console said no"));

    assert.equal(h.logged.length, 1);
    assert.match(h.logged[0].title, /unhandled failure: the console said no/);
    // The stack is what made the previous crash a five-minute fix.
    assert.match(h.logged[0].detail, /crashReport\.test\.js/);
    assert.match(h.crashLog(), /unhandledRejection/);
  } finally {
    h.cleanup();
  }
});

test("a main-process exception is recorded, and the Electron dialog is left alone", () => {
  const h = harness();
  try {
    h.proc.emit("uncaughtException", new Error("span is not defined"));
    assert.equal(h.logged[0].type, "app_crashed");
    assert.match(h.logged[0].title, /span is not defined/);
    // Additive: Electron installs its own listener for this and shows the
    // dialog. If this module ever starts exiting or swallowing, that
    // dialog -- the thing that made yesterday's crash diagnosable --
    // quietly stops being the app's behaviour.
    assert.equal(h.proc.listenerCount("uncaughtException"), 1, "this module must not be the only handler by design");
  } finally {
    h.cleanup();
  }
});

test("a clean quit is recorded too, so it can be told apart from a crash", () => {
  // The whole reason this case exists: from outside, "crashed" and "was
  // told to quit" both look like a window disappearing, and they lead to
  // completely different investigations.
  const h = harness();
  try {
    h.app.emit("before-quit");
    assert.equal(h.logged[0].type, "app_quit");
    assert.match(h.crashLog(), /quit/);
  } finally {
    h.cleanup();
  }
});

test("a dead window or helper process names which one and why", () => {
  const h = harness();
  try {
    h.app.emit("render-process-gone", {}, {}, { reason: "oom", exitCode: 9 });
    h.app.emit("child-process-gone", {}, { type: "GPU", reason: "crashed", exitCode: 139 });
    assert.match(h.logged[0].title, /window's process stopped \(oom\)/);
    assert.match(h.logged[1].title, /helper process stopped \(GPU: crashed\)/);
    assert.match(h.logged[1].detail, /139/);
  } finally {
    h.cleanup();
  }
});

test("a reporter that can't write still doesn't become the crash", () => {
  // It runs while the app is already falling over. A throw in here turns
  // one lost diagnosis into two.
  const proc = new EventEmitter();
  const app = new EventEmitter();
  installCrashReporting({
    proc,
    app,
    logEvent: () => { throw new Error("the log store is broken too"); },
    userDataDir: "/definitely/not/a/real/directory",
  });
  assert.doesNotThrow(() => proc.emit("uncaughtException", new Error("original problem")));
});

test("a non-Error rejection still says something useful", () => {
  // Rejecting with a string or undefined is common in library code, and
  // `payload.message` is undefined for those.
  assert.match(describeExit("unhandledRejection", "just a string").title, /just a string/);
  assert.equal(describeExit("unhandledRejection", undefined).detail, "undefined");
});
