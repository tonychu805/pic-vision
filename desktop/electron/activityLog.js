// Real activity history for the desktop app's "Log" tab (2026-09-05,
// replacing the mock "Alerts" page). Deliberately dependency-free (only
// electron-store) so every other module -- cloud.js, capture.js,
// calibration.js, pipeline.js, auth.js -- can import logEvent() without
// any circular-import risk between them.
//
// Every event type here is a real, already-computed signal somewhere in
// the app; this module is purely the persistence + retrieval layer, not
// new detection logic. See DECISIONS.md/progress notes 2026-09-05 for why
// a few of the original mockup's alert types (saved credential sets,
// firmware-update checking, NTP clock drift) aren't represented here --
// none of them correspond to anything this app actually does.
import { randomUUID } from "node:crypto";
import Store from "electron-store";

const store = new Store({ name: "activityLog" });

// Bounded so this can't grow forever on a machine that runs for months --
// same reasoning as capture.js's segmented recordings, just for a JSON
// list instead of video files.
const MAX_EVENTS = 200;

export function logEvent(type, title, detail = null) {
  const events = store.get("events", []);
  events.unshift({ id: randomUUID(), type, title, detail, at: new Date().toISOString() });
  store.set("events", events.slice(0, MAX_EVENTS));
}

export function getEvents() {
  return store.get("events", []);
}

export function clearEvents() {
  store.set("events", []);
}
