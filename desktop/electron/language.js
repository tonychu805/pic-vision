// The app's language, kept in the main process.
//
// Order: the operator's saved choice, else the system language
// (app.getLocale()), else Traditional Chinese. The choice is stored in the
// app's own settings file, next to power and scan settings, so it survives a
// restart. The renderer reads and sets it over IPC; the tray and anything else
// main shows reads it from here.
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

export function setLanguage(lang) {
  if (!LANGS.includes(lang)) throw new Error(`Unsupported language: ${lang}`);
  store.set("lang", lang);
  for (const listener of listeners) {
    try { listener(lang); } catch (err) { console.error(`[language] listener failed: ${err.message}`); }
  }
  return lang;
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
