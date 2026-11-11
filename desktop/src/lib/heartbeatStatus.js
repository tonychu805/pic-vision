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

import { translator } from "../../electron/i18n/index.js";

const english = translator("en");

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// Matches HEARTBEAT_INTERVAL_MS (60s) x 3, the console's own offline threshold.
const STALE_AFTER_MS = 3 * MINUTE;

/**
 * "just now" / "4 minutes ago" / "2 hours ago" / "3 days ago".
 *
 * Deliberately coarse. The exact second of a check-in is noise to an
 * operator; whether it was a moment ago or yesterday is the whole
 * question. A future timestamp (a machine whose clock is behind the
 * console's) reads as "just now" rather than as a negative age.
 */
export function timeAgo(iso, now = Date.now(), tr = english) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const elapsed = now - then;
  if (elapsed < MINUTE) return tr("ago.justNow");
  if (elapsed < HOUR) {
    const minutes = Math.floor(elapsed / MINUTE);
    return minutes === 1 ? tr("ago.minute") : tr("ago.minutes", { n: minutes });
  }
  if (elapsed < DAY) {
    const hours = Math.floor(elapsed / HOUR);
    return hours === 1 ? tr("ago.hour") : tr("ago.hours", { n: hours });
  }
  const days = Math.floor(elapsed / DAY);
  return days === 1 ? tr("ago.day") : tr("ago.days", { n: days });
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
export function heartbeatStatus(connection, now = Date.now(), tr = english) {
  if (!connection) return null;

  const { brandName, lastAttemptOk, lastHeartbeatAt, removed } = connection;

  // The console refused this machine three times running: it was removed
  // from the venue there (2026-09-29). Not "Connection lost" -- that reads as
  // a network problem that fixes itself, and this one only a person can fix.
  // `canReconnect` is what puts the button on the page.
  if (removed) {
    return {
      tone: "lost",
      title: tr("hb.removed.title", { brand: brandName }),
      detail: tr("hb.removed.detail"),
      canReconnect: true,
    };
  }

  // No attempt has completed yet -- a launch, or a registration a moment
  // ago. Saying "Connected" here is the same guess that caused this
  // ticket, just a shorter-lived one, so it says what it actually knows.
  if (lastAttemptOk == null) {
    return {
      tone: "pending",
      title: tr("hb.pending.title", { brand: brandName }),
      detail: tr("hb.pending.detail"),
    };
  }

  // "The last attempt didn't fail" is not "it is checking in": an attempt that
  // never finishes never fails either. 2026-09-21: a venue machine stopped
  // reaching the console for 30+ minutes while this said Connected, because
  // the heartbeat was stuck waiting rather than erroring, so there was no
  // failure to report. The only honest signal left is the clock -- the last
  // *success* is too old. Three beats is what the console itself tolerates
  // (overview-client.tsx's OFFLINE_AFTER_MS), so the two sides agree on when
  // this machine has gone quiet.
  const lastMs = lastHeartbeatAt ? Date.parse(lastHeartbeatAt) : NaN;
  if (lastAttemptOk && Number.isFinite(lastMs) && now - lastMs > STALE_AFTER_MS) {
    return {
      tone: "lost",
      title: tr("hb.stuck.title", { brand: brandName }),
      detail: tr("hb.stuck.detail", { ago: timeAgo(lastHeartbeatAt, now, tr) }),
    };
  }

  if (lastAttemptOk) {
    const ago = lastHeartbeatAt ? timeAgo(lastHeartbeatAt, now, tr) : null;
    return {
      tone: "ok",
      title: tr("hb.ok.title", { brand: brandName }),
      // Checks in every 30 seconds, so this reads "just now" almost always;
      // it earns its place on the rare occasion it doesn't.
      detail: ago ? tr("hb.ok.detail", { ago }) : tr("hb.ok.detailNone"),
    };
  }

  const ago = lastHeartbeatAt ? timeAgo(lastHeartbeatAt, now, tr) : null;
  return {
    tone: "lost",
    title: tr("hb.lost.title"),
    // Never checked in successfully vs. checked in an hour ago are
    // different problems -- the first is usually a wrong console URL or a
    // revoked machine, the second a network that dropped.
    detail: ago
      ? tr("hb.lost.detail", { ago })
      : tr("hb.lost.detailNever", { brand: brandName }),
  };
}

/**
 * The sidebar's one-line version of the same answer (2026-09-29).
 *
 * The sidebar box used to say "Connected" about the local network -- right
 * where anyone looks for "is this machine connected", and it went on saying
 * it while the console had removed the machine or couldn't be reached.
 * Derived from heartbeatStatus so the two can never disagree; only the
 * wording is shorter, since the sidebar is 196px wide.
 */
export function sidebarConnection(connection, now = Date.now(), tr = english) {
  if (connection === undefined) return { tone: "pending", title: tr("side.checking"), detail: null };
  if (connection === null) return { tone: "lost", title: tr("side.notConnected"), detail: tr("side.notConnectedDetail") };
  const full = heartbeatStatus(connection, now, tr);
  if (full.canReconnect) return { tone: "lost", title: tr("side.removed"), detail: tr("side.removedDetail") };
  if (full.tone === "ok") return { tone: "ok", title: tr("side.connected"), detail: full.detail };
  if (full.tone === "pending") return { tone: "pending", title: tr("side.connecting"), detail: tr("side.connectingDetail") };
  if (connection.lastAttemptOk) return { tone: "lost", title: tr("side.notChecking"), detail: tr("side.detailsHint") };
  return { tone: "lost", title: tr("side.lost"), detail: tr("side.detailsHint") };
}
