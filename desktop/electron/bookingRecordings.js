// What this machine is recording for a booking, and until when -- kept on
// disk, so a booking's recording no longer depends on the internet or on
// the app staying up (2026-09-29).
//
// Before this, a booking's recording ended only when the console's stop
// command arrived. The machine never knew when the booking ended. So:
//
//   - internet down at the end of a booking: the recording ran on until it
//     came back, and the next group's play landed under the first group's
//     share link, while the next group's own recording started late;
//   - app restarted mid-booking: quitting stopped the recording cleanly,
//     nothing restarted it, and when the booking's stop arrived there was
//     nothing recording, so what HAD been recorded was never sent;
//   - machine off for the whole booking: its start and stop both ran on
//     return, back to back, and sent a few seconds of video to a GPU.
//
// The console's start now carries the booking's end time (`ends_at`). The
// machine notes it here, stops the recording itself at that time
// (cloud.js's bookingEndTick), picks it back up after a restart
// (recoverRecordingsAfterRestart), and ignores a start that arrives after
// its booking is over. The console's own stop still comes; it stops the
// recording if it's still running and marks the note, nothing more.
//
// The note is kept until the recording has actually REACHED the console,
// not merely until a send was tried. Stopping on time is exactly what
// happens when the internet is down, and a send attempted then fails --
// before this, the late stop only ever arrived once the internet was back,
// so its send worked. Only bookingEndTick sends, retrying every
// SEND_RETRY_MS until the console has the job.
//
// Deliberately only bookings. A recording started by hand has no end time
// and behaves exactly as before.
import Store from "electron-store";

const store = new Store({ name: "bookingRecordings", configFileMode: 0o600 });

/** A booking start's end time in ms, or null when it doesn't carry one (older console, or a hand start). */
export function bookingEndsAt(params) {
  const t = Date.parse(params?.ends_at ?? "");
  return Number.isFinite(t) ? t : null;
}

/** A booking start that reached this machine only after its booking had ended. */
export function startArrivedTooLate(params, now = Date.now()) {
  const end = bookingEndsAt(params);
  return end != null && now >= end;
}

// How often a send that didn't reach the console is tried again.
export const SEND_RETRY_MS = 60_000;

export function noteBookingRecording({ cameraId, bookingId, endsAt, outDir }) {
  store.set("byCamera", { ...store.get("byCamera", {}), [cameraId]: { cameraId, bookingId, endsAt, outDir, stopped: false, lastSendAt: null } });
}

export function listBookingRecordings() {
  return Object.values(store.get("byCamera", {}));
}

function keyOf(all, { cameraId, outDir, bookingId }) {
  return Object.keys(all).find((k) => {
    const n = all[k];
    if (bookingId) return n.bookingId === bookingId;
    return n.cameraId === cameraId && n.outDir === outDir;
  });
}

/** The note for one recording -- by camera and folder, or by booking -- or null. */
export function findBookingRecording(match) {
  const all = store.get("byCamera", {});
  const key = keyOf(all, match);
  return key ? all[key] : null;
}

/** Merge `patch` into a note, if it's still there. Returns the updated note or null. */
export function updateBookingRecording(match, patch) {
  const all = store.get("byCamera", {});
  const key = keyOf(all, match);
  if (!key) return null;
  all[key] = { ...all[key], ...patch };
  store.set("byCamera", all);
  return all[key];
}

export function forgetBookingRecording(match) {
  const all = store.get("byCamera", {});
  const key = keyOf(all, match);
  if (!key) return;
  delete all[key];
  store.set("byCamera", all);
}

/** Notes that should be stopped and sent now: the booking is over, or the console already stopped it. */
export function bookingsToFinish(notes, now = Date.now()) {
  return notes.filter((n) => {
    if (n.stopped) return true;
    const end = bookingEndsAt({ ends_at: n.endsAt });
    return end != null && now >= end;
  });
}

/** Time for another send attempt? The first one is always due. */
export function sendDue(note, now = Date.now(), retryMs = SEND_RETRY_MS) {
  return !note.lastSendAt || now - note.lastSendAt >= retryMs;
}

/**
 * What to do with each note when the app starts:
 *
 *   resume -- the booking is still on: carry on recording into its folder
 *   finish -- the booking ended while the app was down: send what was recorded
 *   drop   -- the camera or the folder is gone: nothing to resume or send
 *
 * Pure, so every branch is testable without a store, a camera or ffmpeg.
 */
export function planAfterRestart(notes, now, { cameraIds, folderExists }) {
  return notes.map((note) => {
    if (!cameraIds.has(note.cameraId) || !folderExists(note.outDir)) return { note, action: "drop" };
    if (note.stopped) return { note, action: "finish" };
    const end = bookingEndsAt({ ends_at: note.endsAt });
    if (end == null) return { note, action: "drop" };
    return { note, action: now >= end ? "finish" : "resume" };
  });
}
