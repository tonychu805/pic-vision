// Renderer-side failures, made reportable.
//
// 2026-09-20: clicking Retry made the app "just disappear" -- no dialog,
// no crash log, nothing on stderr, and the process still alive. It turned
// out nothing had crashed at all. An error in the React tree unmounted
// the whole root (there was no error boundary), and because the window is
// deliberately transparent with no background of its own -- frame: false,
// transparent: true, so App.jsx can draw its own rounded corners -- an
// unmounted tree is not a blank window. It is an invisible one. You see
// the desktop through it.
//
// So the renderer could fail completely while main.js's crash reporting
// (ADR-106) sat there with nothing to report: it covers the main process,
// and this happened in the other one.
//
// Pure functions here, DOM wiring injected, so this is testable under
// plain `node --test` like the rest of src/lib -- the harness has no
// jsdom and no React testing library, and ADR-105's lesson is that logic
// nobody executes in a test is logic nobody has checked.

/**
 * An error, flattened into the two strings the main process stores.
 *
 * The stack is the field that matters: ADR-105's crash was diagnosed from
 * its `file:line` alone. React's component stack is appended when there is
 * one, because "which component threw" is the renderer's equivalent of
 * that, and it is not part of the JS stack.
 */
export function formatRendererError(error, componentStack = null) {
  const message =
    (typeof error === "string" && error) ||
    error?.message ||
    (error === undefined ? "undefined" : String(error));
  const parts = [];
  if (error?.stack) parts.push(error.stack);
  if (componentStack) parts.push(`Component stack:${componentStack}`);
  return { message, stack: parts.length ? parts.join("\n\n") : null };
}

/**
 * Wires up the two failures that never reach a React error boundary: a
 * plain `window.onerror` throw (an event handler, a timer) and a promise
 * nobody caught. Both are otherwise silent -- they print to a DevTools
 * console nobody has open.
 *
 * `report` failing is swallowed. This runs while something is already
 * broken, and a reporter that throws turns one lost diagnosis into two --
 * the same rule crashReport.js follows in the main process.
 */
export function installRendererErrorReporting({ target, report }) {
  const safely = (payload) => {
    try {
      report(payload);
    } catch { /* already broken */ }
  };
  target.addEventListener("error", (event) => {
    safely(formatRendererError(event?.error ?? event?.message ?? "unknown error"));
  });
  target.addEventListener("unhandledrejection", (event) => {
    safely(formatRendererError(event?.reason ?? "unknown rejection"));
  });
}
