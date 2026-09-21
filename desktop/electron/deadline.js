// A deadline for a promise that has none of its own.
//
// Why this exists (2026-09-21): the venue agent's command pass and heartbeat
// each `await` several network calls and a camera probe with no time limit.
// One call that never settled -- a stalled upload, a camera that accepts the
// connection and says nothing -- froze the pass, and the pass runs one
// command at a time, so everything behind it waited forever. The heartbeat
// tick used to await the pass before sending, so the console went dark too,
// while the app kept saying "Connected" because nothing had *failed*. A hang
// is not a failure, so nothing was logged.
//
// This does not cancel the underlying work (a promise cannot be cancelled);
// it stops the caller waiting on it, which is what unfreezes the queue. Work
// that can be aborted for real (fetch, sockets) should still be aborted at
// its own level -- this is the backstop for the step nobody thought could
// hang.
export class DeadlineError extends Error {
  constructor(what, ms) {
    super(`${what} did not finish within ${Math.round(ms / 1000)}s`);
    this.name = "DeadlineError";
    this.what = what;
    this.ms = ms;
  }
}

export function withDeadline(promise, ms, what) {
  let timer;
  const deadline = new Promise((_, reject) => {
    // Deliberately NOT unref'd: a deadline that can be skipped because
    // nothing else is holding the process open is not a deadline. It cannot
    // outlive the step it guards -- it is cleared the moment that settles.
    timer = setTimeout(() => reject(new DeadlineError(what, ms)), ms);
  });
  // If the deadline wins, the original promise may still reject later; that
  // rejection has been abandoned on purpose and must not surface as unhandled.
  promise.catch(() => {});
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}
