// PIC-92: what the Cloud page says about the link to the console.
//
// It used to say "Connected to <venue>" whenever a connection existed in
// local storage, which answers "was this machine ever registered" -- not
// "is it reporting right now". After a real revoke the page kept saying
// Connected, with a stale "Registered ..." line, while every heartbeat was
// being rejected; the only honest account was in the Log tab, which an
// operator glancing at the Cloud page has no reason to open.
//
// All of the branching lives here, as a pure function, so it can be tested
// without a browser -- but note what that cost last time (ADR-105): nine
// green tests of an extracted helper while nothing ran the function around
// it. So this returns the finished strings the page prints, not a code the
// page then maps to strings itself. If the wording is wrong, these tests
// are wrong; there is no second copy of the decision in the JSX.

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * "just now" / "4 minutes ago" / "2 hours ago" / "3 days ago".
 *
 * Deliberately coarse. The exact second of a check-in is noise to an
 * operator; whether it was a moment ago or yesterday is the whole
 * question. A future timestamp (a machine whose clock is behind the
 * console's) reads as "just now" rather than as a negative age.
 */
export function timeAgo(iso, now = Date.now()) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const elapsed = now - then;
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) {
    const minutes = Math.floor(elapsed / MINUTE);
    return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  }
  if (elapsed < DAY) {
    const hours = Math.floor(elapsed / HOUR);
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  const days = Math.floor(elapsed / DAY);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/**
 * Turn a `cloud:status` reply into what the page shows.
 *
 * `connection` is that reply: undefined while the first read is in flight,
 * null when this machine isn't registered at all, otherwise the stored
 * record plus `lastAttemptOk` / `lastHeartbeatAt` from the heartbeat loop.
 *
 * Returns `null` for the two cases the page already handles with its own
 * layout (still loading, and not registered) rather than inventing a
 * status line for them.
 */
export function heartbeatStatus(connection, now = Date.now()) {
  if (!connection) return null;

  const { brandName, lastAttemptOk, lastHeartbeatAt } = connection;

  // No attempt has completed yet -- a launch, or a registration a moment
  // ago. Saying "Connected" here is the same guess that caused this
  // ticket, just a shorter-lived one, so it says what it actually knows.
  if (lastAttemptOk == null) {
    return {
      tone: "pending",
      title: `Connecting to ${brandName}…`,
      detail: "Waiting for this machine's first check-in.",
    };
  }

  if (lastAttemptOk) {
    const ago = lastHeartbeatAt ? timeAgo(lastHeartbeatAt, now) : null;
    return {
      tone: "ok",
      title: `Connected to ${brandName}`,
      // Checks in every 30 seconds, so this reads "just now" almost always;
      // it earns its place on the rare occasion it doesn't.
      detail: ago ? `Last check-in ${ago}.` : "Checked in.",
    };
  }

  const ago = lastHeartbeatAt ? timeAgo(lastHeartbeatAt, now) : null;
  return {
    tone: "lost",
    title: "Connection lost",
    // Never checked in successfully vs. checked in an hour ago are
    // different problems -- the first is usually a wrong console URL or a
    // revoked machine, the second a network that dropped.
    detail: ago
      ? `Last successful check-in ${ago}. The Log tab has the reason.`
      : `This machine has not checked in to ${brandName} successfully yet. The Log tab has the reason.`,
  };
}
