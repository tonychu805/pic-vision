// The app's language, kept in the main process.
//
// It is the venue's language (operator 2026-11-16: set in the console, no
// switch in this app), learned at registration and on every heartbeat and
// stored here so it survives a restart and an offline console. Before this
// machine has heard from its venue: the system language (app.getLocale()),
// else Traditional Chinese. The renderer reads it and is told of changes over
// IPC; the tray and anything else main shows reads it from here.
import { app } from "electron";
import Store from "electron-store";
import { LANGS, pickLang, translator } from "./i18n/index.js";

const store = new Store({ name: "language", configFileMode: 0o600 });
const listeners = new Set();

function systemLocale() {
  try {
    return app.getLocale();
  } catch {
    return "";
  }
}

export function getLanguage() {
  return pickLang(store.get("lang", null), systemLocale());
}

function setLanguage(lang) {
  if (!LANGS.includes(lang)) throw new Error(`Unsupported language: ${lang}`);
  store.set("lang", lang);
  for (const listener of listeners) {
    try { listener(lang); } catch (err) { console.error(`[language] listener failed: ${err.message}`); }
  }
  return lang;
}

/** The console's brandLanguage, from a registration or heartbeat reply; anything else is ignored. */
export function followVenueLanguage(lang) {
  if (LANGS.includes(lang) && lang !== store.get("lang", null)) setLanguage(lang);
}

/** Run `fn(lang)` after every change, so the tray can redraw at once. */
export function onLanguageChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Translate for the main process's own user-facing text, in the current language. */
export function tm(key, vars) {
  return translator(getLanguage())(key, vars);
}
