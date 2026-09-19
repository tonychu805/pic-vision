// Why the app died, written down before it dies.
//
// 2026-09-19/20: the operator hit a crash with no error text at all --
// "it just disappears". That is a worse position than the ReferenceError
// dialog the day before, which named a file and a line and was fixed in
// minutes. A failure that reports nothing costs a round trip to the
// person who hit it, and they may not be able to reproduce it on demand.
//
// So this isn't about any one bug. It converts every way the app can go
// away into a line in the Log tab and a line in a plain text file, and it
// distinguishes the cases that look identical from outside:
//
//   uncaughtException    a JS error in the main process
//   unhandledRejection   a promise nobody caught -- the one that can kill
//                        the process with no dialog at all, since Node's
//                        default here is to throw
//   render-process-gone  the window's own process died (a blank window,
//                        or nothing)
//   child-process-gone   a GPU/utility process died
//   quit                 nobody crashed; something asked the app to exit
//
// That last one is the whole point of logging a clean quit too: "crashed"
// and "was told to quit" are indistinguishable to someone watching a
// window vanish, and they lead to completely different investigations.
//
// NOT covered, deliberately, because it cannot be: a native crash in the
// main process itself. No JavaScript runs after that. macOS writes those
// to ~/Library/Logs/DiagnosticReports, which is where to look when this
// file recorded nothing at all -- itself a useful signal.
import { appendFileSync } from "node:fs";
import path from "node:path";

export const CRASH_LOG = "crash.log";

/**
 * One event, formatted for both destinations. Pure, so the wording is
 * testable without staging a real crash.
 *
 * `detail` carries the stack when there is one: the previous crash was
 * diagnosed from its stack's file:line alone, so it is the single most
 * valuable field here and is never trimmed away.
 */
export function describeExit(kind, payload) {
  switch (kind) {
    case "uncaughtException":
      return {
        type: "app_crashed",
        title: `The app hit an unexpected error: ${payload?.message ?? payload}`,
        detail: payload?.stack ?? String(payload),
      };
    case "unhandledRejection":
      return {
        type: "app_crashed",
        // Named differently from the case above on purpose. A rejection
        // nobody handled can take the process down with no dialog, which
        // is the failure shape that is hardest to report from the outside.
        title: `The app hit an unhandled failure: ${payload?.message ?? payload}`,
        detail: payload?.stack ?? String(payload),
      };
    case "renderer-error":
      return {
        type: "app_crashed",
        // Distinct from render-process-gone: the window's process is
        // alive and well, its React tree just died. With a transparent
        // window that looks identical to the app vanishing, which is
        // exactly how it was reported.
        title: `The app window hit an error: ${payload?.message ?? payload}`,
        detail: payload?.stack ?? null,
      };
    case "render-process-gone":
      return {
        type: "app_crashed",
        title: `The app window's process stopped (${payload?.reason ?? "unknown reason"})`,
        detail: `exitCode ${payload?.exitCode ?? "?"}`,
      };
    case "child-process-gone":
      return {
        type: "app_crashed",
        title: `A helper process stopped (${payload?.type ?? "unknown"}: ${payload?.reason ?? "unknown reason"})`,
        detail: `exitCode ${payload?.exitCode ?? "?"}${payload?.name ? `, ${payload.name}` : ""}`,
      };
    case "quit":
      return {
        type: "app_quit",
        title: "The app was asked to quit",
        detail: payload?.reason ?? null,
      };
    default:
      return { type: "app_crashed", title: `The app stopped (${kind})`, detail: payload ? String(payload) : null };
  }
}

/**
 * Installs the handlers. Everything it touches is injected so the whole
 * thing can be exercised in a test rather than by staging a real crash --
 * the gap that let ADR-105's bug ship was a function no test ever ran.
 *
 * `logEvent` failures are swallowed: this runs while the app is already
 * falling over, and a crash reporter that throws inside a crash handler
 * turns one lost diagnosis into two.
 */
export function installCrashReporting({
  proc = process,
  app,
  logEvent,
  userDataDir,
  now = () => new Date().toISOString(),
} = {}) {
  const record = (kind, payload) => {
    const { type, title, detail } = describeExit(kind, payload);
    try {
      logEvent?.(type, title, detail);
    } catch { /* already crashing */ }
    try {
      if (userDataDir) {
        appendFileSync(
          path.join(userDataDir, CRASH_LOG),
          `${now()}  ${kind}  ${title}\n${detail ? `${detail}\n` : ""}\n`,
        );
      }
    } catch { /* already crashing */ }
    // stderr as well: the fastest way anyone diagnoses this is launching
    // the .app from a terminal, and that only shows what was printed.
    try {
      console.error(`[crash] ${kind}: ${title}${detail ? `\n${detail}` : ""}`);
    } catch { /* already crashing */ }
  };

  // Additive, not a replacement: Electron installs its own
  // uncaughtException listener that shows the "A JavaScript error occurred
  // in the main process" dialog, and both listeners run. Deliberately does
  // NOT exit -- that dialog and its behaviour stay exactly as they were.
  proc.on("uncaughtException", (err) => record("uncaughtException", err));

  // This one DOES change behaviour, knowingly. Node 22's default for an
  // unhandled rejection is to throw, which can take the process down; with
  // a listener attached it doesn't. Staying alive with a logged failure is
  // better than vanishing with nothing, and it is the shape the operator
  // actually hit.
  proc.on("unhandledRejection", (reason) => record("unhandledRejection", reason));

  app?.on?.("render-process-gone", (_event, _contents, details) => record("render-process-gone", details));
  app?.on?.("child-process-gone", (_event, details) => record("child-process-gone", details));
  // Logged so a clean exit can be told apart from a crash. Without this,
  // "the window disappeared" has two very different explanations and no
  // way to choose between them.
  app?.on?.("before-quit", () => record("quit", null));

  return record;
}
