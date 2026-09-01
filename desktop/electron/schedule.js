// Per-camera booked sessions -- discrete day-of-week + hour-range blocks
// (start inclusive, end exclusive: "1-2pm" is {start:13, end:14}), not a
// flat "hour is active" set. A flat set can't represent the boundary
// between two back-to-back bookings (1-2pm for one person, 2-4pm for
// another) -- they'd merge into one indistinguishable 1-4pm block. Once
// real capture + detection exist (PIC-66/69), each session is meant to
// become its own highlight-reel job, so the boundary has to survive even
// when sessions touch with zero gap between them.
//
// Still config/storage only -- nothing consumes this yet, see the header
// comment in the previous cell-based version of this file (superseded
// 2026-09-01) and STRATEGY.md §5.
import Store from "electron-store";
import { randomUUID } from "node:crypto";

const store = new Store({ name: "schedules" });

function isValidRange(day, start, end) {
  return (
    Number.isInteger(day) && day >= 0 && day <= 6 &&
    Number.isInteger(start) && start >= 0 && start < 24 &&
    Number.isInteger(end) && end > start && end <= 24
  );
}

export function listSessions(cameraId) {
  const all = store.get("schedules", {});
  return all[cameraId]?.sessions ?? [];
}

function saveSessions(cameraId, sessions) {
  const all = store.get("schedules", {});
  all[cameraId] = { sessions };
  store.set("schedules", all);
  return sessions;
}

// Removes [start, end) on `day` from any existing session, splitting a
// session that's only partly overlapped and dropping one that's fully
// consumed -- so committing a new session can never leave two sessions
// silently overlapping the same hour.
function subtractRange(sessions, day, start, end) {
  const result = [];
  for (const s of sessions) {
    if (s.day !== day || s.end <= start || s.start >= end) {
      result.push(s); // different day, or no overlap at all
      continue;
    }
    const keepsLeft = s.start < start;
    if (keepsLeft) result.push({ ...s, end: start });
    if (s.end > end) result.push({ ...s, id: keepsLeft ? randomUUID() : s.id, start: end });
    // else: s is fully inside [start,end) -- fully consumed, dropped
  }
  return result;
}

export function addSession(cameraId, { day, start, end, label }) {
  if (!isValidRange(day, start, end)) throw new Error("invalid session range");
  const cleared = subtractRange(listSessions(cameraId), day, start, end);
  const session = { id: randomUUID(), day, start, end, label: label || null };
  return saveSessions(cameraId, [...cleared, session]);
}

export function removeSession(cameraId, sessionId) {
  return saveSessions(cameraId, listSessions(cameraId).filter((s) => s.id !== sessionId));
}

export function renameSession(cameraId, sessionId, label) {
  const next = listSessions(cameraId).map((s) => (s.id === sessionId ? { ...s, label: label || null } : s));
  return saveSessions(cameraId, next);
}

export function listSchedules() {
  return store.get("schedules", {});
}

export function removeSchedule(cameraId) {
  const all = store.get("schedules", {});
  delete all[cameraId];
  store.set("schedules", all);
}
