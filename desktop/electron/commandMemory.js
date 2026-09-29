// The commands this machine has already carried out, and what came of each
// (2026-09-29).
//
// A command stays `pending` on the console until the machine reports its
// result. If that report never arrives -- a dropped connection, a timeout,
// the app quitting between doing the work and saying so -- the next sweep
// hands the same command over again, and it used to be run again. For a
// stop that's harmless; for a start it read as "Already recording"; for a
// calibration snapshot it took and uploaded another picture of the room;
// and for send_to_cloud it could send the clip a second time: another GPU
// job and duplicate reels.
//
// Now the result is written down here the moment the work is done, before
// it's reported, and a command seen again is answered from here instead of
// being run. On disk, so a restart between the work and the report is
// covered too.
import Store from "electron-store";

// Plenty: a command only comes back while its report is outstanding, which
// is minutes, and the busiest day on record was a few dozen commands.
export const REMEMBERED_COMMANDS = 50;

const store = new Store({ name: "commandResults", configFileMode: 0o600 });

/** What happened to this command the first time, or null if it's new. */
export function rememberedResult(commandId) {
  return store.get("byId", {})[commandId] ?? null;
}

export function rememberResult(commandId, status, result, now = Date.now()) {
  store.set("byId", keepNewest({ ...store.get("byId", {}), [commandId]: { status, result: result ?? null, at: now } }, REMEMBERED_COMMANDS));
}

/** The `limit` most recent entries. Pure, for the test. */
export function keepNewest(byId, limit) {
  return Object.fromEntries(Object.entries(byId).sort(([, a], [, b]) => b.at - a.at).slice(0, limit));
}
