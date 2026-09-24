// Keeping a venue computer ready (2026-09-24).
//
// A capture box has to be awake for a booking's start command to reach it,
// and awake while it records and uploads. macOS puts an idle Mac to sleep;
// this holds a "don't sleep" request for as long as the app runs (the
// display can still turn off). And it opens the app at login, so a restart
// -- a macOS update, a power cut with "start up after a power failure" on
// brings it back with nobody touching it. Both on by default; either can be
// turned off in Settings (a personal laptop may not want them).
//
// What no app can override: a MacBook's closed lid (sleeps unless on power
// with an external display), a power cut without that Energy setting, or
// someone quitting the app.
import { app, powerSaveBlocker } from "electron";
import Store from "electron-store";

const store = new Store({ name: "power", configFileMode: 0o600 });
let blockerId = null;

export function getPowerSettings() {
  return {
    keepAwake: store.get("keepAwake", true) !== false,
    openAtLogin: store.get("openAtLogin", true) !== false,
    // Only a packaged app can be a login item; `npm run dev` would register the bare Electron binary.
    loginItemAvailable: app.isPackaged,
  };
}

export function applyPowerSettings() {
  const { keepAwake, openAtLogin } = getPowerSettings();
  if (keepAwake && blockerId === null) {
    blockerId = powerSaveBlocker.start("prevent-app-suspension");
  } else if (!keepAwake && blockerId !== null) {
    powerSaveBlocker.stop(blockerId);
    blockerId = null;
  }
  if (app.isPackaged) app.setLoginItemSettings({ openAtLogin });
}

export function setKeepAwake(on) {
  store.set("keepAwake", Boolean(on));
  applyPowerSettings();
  return getPowerSettings();
}

export function setOpenAtLogin(on) {
  store.set("openAtLogin", Boolean(on));
  applyPowerSettings();
  return getPowerSettings();
}
