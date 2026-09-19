// The renderer's half of crash reporting, exercised.
//
// Same rule as crashReport.test.js and for the same reason (ADR-105): run
// the wiring, don't just check the formatter beside it. The whole failure
// being fixed here is one where nothing ran and nothing was reported.
import assert from "node:assert/strict";
import { test } from "node:test";
// EventTarget/Event are globals in Node 22, the same shape the real
// `window` provides -- so this exercises the actual addEventListener
// wiring rather than a bespoke stub of it.
import { formatRendererError, installRendererErrorReporting } from "./rendererErrors.js";

function harness() {
  const target = new EventTarget();
  const reports = [];
  installRendererErrorReporting({ target, report: (payload) => reports.push(payload) });
  return { target, reports };
}

test("a thrown error outside React is reported with its stack", () => {
  // window.onerror territory: an event handler or a timer. No error
  // boundary ever sees these, and they print to a DevTools console
  // nobody has open.
  const { target, reports } = harness();
  const event = new Event("error");
  event.error = new Error("pipeline run exploded");
  target.dispatchEvent(event);

  assert.equal(reports.length, 1);
  assert.equal(reports[0].message, "pipeline run exploded");
  assert.match(reports[0].stack, /rendererErrors\.test\.js/);
});

test("a promise nobody caught is reported too", () => {
  const { target, reports } = harness();
  const event = new Event("unhandledrejection");
  event.reason = new Error("the console didn't answer");
  target.dispatchEvent(event);
  assert.equal(reports[0].message, "the console didn't answer");
});

test("a reporter that throws doesn't become the failure", () => {
  // It runs while the app is already broken.
  const target = new EventTarget();
  installRendererErrorReporting({
    target,
    report: () => { throw new Error("IPC is gone too"); },
  });
  const event = new Event("error");
  event.error = new Error("original problem");
  assert.doesNotThrow(() => target.dispatchEvent(event));
});

test("React's component stack is kept alongside the JS stack", () => {
  // "Which component threw" is the renderer's equivalent of the
  // file:line that made ADR-105 a five-minute fix, and it is not part of
  // the JS stack.
  const { message, stack } = formatRendererError(
    new Error("cannot read properties of undefined"),
    "\n    at CloudJobRow\n    at CameraDetailPage",
  );
  assert.equal(message, "cannot read properties of undefined");
  assert.match(stack, /Component stack:/);
  assert.match(stack, /CloudJobRow/);
});

test("things thrown that aren't Errors still say something", () => {
  assert.equal(formatRendererError("a bare string").message, "a bare string");
  assert.equal(formatRendererError(undefined).message, "undefined");
  assert.equal(formatRendererError(null).message, "null");
  assert.equal(formatRendererError({ code: 42 }).message, "[object Object]");
  // No stack to report is null, not the string "undefined".
  assert.equal(formatRendererError("a bare string").stack, null);
});
