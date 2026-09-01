// Per-camera weekly activation schedule -- when the (not-yet-built, PIC-66)
// capture/pipeline step should be allowed to run for a given camera.
// Deliberately UI + storage only for now: nothing in this file starts or
// stops a real recording process, because no real process exists yet
// (STRATEGY.md §5's "Local stream/footage management" bullet, PIC-66).
// This is the config a future capture scheduler would read from, built now
// so it's ready to wire up rather than re-designed later.
//
// A schedule is a set of active 1-hour cells across a repeating week, not
// specific calendar dates -- venue operating hours repeat weekly, and a
// fixed 168-cell grid (7 days x 24 hours) is the simplest thing that can't
// grow unbounded the way a per-date log would. Cell key format: "<day>-<hour>",
// day 0=Sunday..6=Saturday (matches JS Date#getDay(), the convention a real
// capture scheduler will need to check against "is it active right now").
import Store from "electron-store";

const store = new Store({ name: "schedules" });

export function isValidCell(cell) {
  const m = /^([0-6])-([0-9]|1[0-9]|2[0-3])$/.exec(cell);
  return m !== null;
}

export function getSchedule(cameraId) {
  const all = store.get("schedules", {});
  return { cameraId, cells: all[cameraId]?.cells ?? [] };
}

export function setSchedule(cameraId, cells) {
  if (!Array.isArray(cells) || !cells.every(isValidCell)) {
    throw new Error("cells must be an array of \"<0-6>-<0-23>\" strings");
  }
  const all = store.get("schedules", {});
  // De-dupe -- a drag gesture can pass the same cell twice.
  all[cameraId] = { cells: [...new Set(cells)] };
  store.set("schedules", all);
  return { cameraId, cells: all[cameraId].cells };
}

export function listSchedules() {
  return store.get("schedules", {});
}

export function removeSchedule(cameraId) {
  const all = store.get("schedules", {});
  delete all[cameraId];
  store.set("schedules", all);
}
