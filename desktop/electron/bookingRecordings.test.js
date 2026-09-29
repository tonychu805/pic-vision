// The booking-recording decisions (bookingRecordings.js), all pure or
// against the in-memory store the test harness provides. No camera, no ffmpeg.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  bookingEndsAt, startArrivedTooLate, bookingsToFinish, sendDue, planAfterRestart, SEND_RETRY_MS,
  noteBookingRecording, findBookingRecording, updateBookingRecording, forgetBookingRecording, listBookingRecordings,
} from "./bookingRecordings.js";

const END = "2026-09-29T14:00:00+00:00";
const endMs = Date.parse(END);

test("a booking start carries its end time; a hand start and an older console's start don't", () => {
  assert.equal(bookingEndsAt({ ends_at: END, schedule_booking_id: "b" }), endMs);
  assert.equal(bookingEndsAt({ schedule_booking_id: "b" }), null);
  assert.equal(bookingEndsAt(null), null);
  assert.equal(bookingEndsAt({ ends_at: "not a time" }), null);
});

test("a start that arrives after its booking ended is refused", () => {
  assert.equal(startArrivedTooLate({ ends_at: END }, endMs), true);
  assert.equal(startArrivedTooLate({ ends_at: END }, endMs + 3 * 3600_000), true);
});

// Paired: the refusal must not catch the ordinary case, or no booking records.
test("a start that arrives during its booking still records, and one without an end time always does", () => {
  assert.equal(startArrivedTooLate({ ends_at: END }, endMs - 1), false);
  assert.equal(startArrivedTooLate({ schedule_booking_id: "b" }, endMs + 3600_000), false);
  assert.equal(startArrivedTooLate(undefined, endMs), false);
});

test("a booking is finished once it's over, or once the console has stopped it", () => {
  const notes = [
    { cameraId: "over", endsAt: END, stopped: false },
    { cameraId: "still-on", endsAt: "2026-09-29T15:00:00+00:00", stopped: false },
    { cameraId: "stopped-early", endsAt: "2026-09-29T15:00:00+00:00", stopped: true },
  ];
  assert.deepEqual(bookingsToFinish(notes, endMs).map((n) => n.cameraId), ["over", "stopped-early"]);
});

// Paired: a booking still on must be left recording.
test("a booking still on, and not stopped, is left alone", () => {
  assert.deepEqual(bookingsToFinish([{ cameraId: "a", endsAt: END, stopped: false }], endMs - 1), []);
});

test("a failed send is retried, but not on every tick", () => {
  assert.equal(sendDue({ lastSendAt: null }, endMs), true); // first attempt: straight away
  assert.equal(sendDue({ lastSendAt: endMs }, endMs + 5_000), false); // next tick: too soon
  assert.equal(sendDue({ lastSendAt: endMs }, endMs + SEND_RETRY_MS), true); // a minute on: try again
});

test("after a restart: resume a booking still on, finish one that ended, drop what's gone", () => {
  const notes = [
    { cameraId: "on", outDir: "/r/on", endsAt: END },
    { cameraId: "over", outDir: "/r/over", endsAt: "2026-09-29T13:00:00+00:00" },
    { cameraId: "removed", outDir: "/r/removed", endsAt: END },
    { cameraId: "on", outDir: "/r/deleted-folder", endsAt: END },
    { cameraId: "on", outDir: "/r/on", endsAt: "garbage" },
    { cameraId: "on", outDir: "/r/on", endsAt: END, stopped: true },
  ];
  const plan = planAfterRestart(notes, endMs - 60_000, {
    cameraIds: new Set(["on", "over"]),
    folderExists: (dir) => dir !== "/r/deleted-folder",
  });
  assert.deepEqual(plan.map((p) => p.action), ["resume", "finish", "drop", "drop", "drop", "finish"]);
});

test("a note is found by its booking or by camera and folder, and stays until forgotten", () => {
  noteBookingRecording({ cameraId: "cam1", bookingId: "b1", endsAt: END, outDir: "/r/1" });
  noteBookingRecording({ cameraId: "cam2", bookingId: "b2", endsAt: END, outDir: "/r/2" });
  assert.equal(findBookingRecording({ bookingId: "b1" })?.outDir, "/r/1");
  assert.equal(findBookingRecording({ cameraId: "cam2", outDir: "/r/2" })?.bookingId, "b2");
  // A different folder on the same camera is a different recording.
  assert.equal(findBookingRecording({ cameraId: "cam2", outDir: "/r/other" }), null);

  // Marking and a send attempt keep the note -- it only goes once the
  // recording has reached the console, which is the point.
  updateBookingRecording({ bookingId: "b1" }, { stopped: true, lastSendAt: endMs });
  assert.deepEqual({ ...findBookingRecording({ bookingId: "b1" }) }, {
    cameraId: "cam1", bookingId: "b1", endsAt: END, outDir: "/r/1", stopped: true, lastSendAt: endMs,
  });

  forgetBookingRecording({ bookingId: "b1" });
  assert.equal(findBookingRecording({ bookingId: "b1" }), null);
  assert.deepEqual(listBookingRecordings().map((n) => n.cameraId), ["cam2"]); // the other camera's is untouched
  assert.equal(updateBookingRecording({ bookingId: "b1" }, { stopped: true }), null); // nothing to update
  forgetBookingRecording({ bookingId: "b2" });
});
