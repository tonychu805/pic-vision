// The renderer's copy of the language, outside React.
//
// ErrorBoundary and the rendererErrors helpers run where no provider is
// mounted (the boundary sits ABOVE it, on purpose: it has to survive the
// provider itself failing), so they read the language from here. The
// provider keeps this in step; until it has asked the main process, the
// system language decides, same as main would.
import { pickLang, t as translate } from "../../electron/i18n/index.js";

let current = pickLang(null, typeof navigator === "undefined" ? "" : navigator.language);
const subscribers = new Set();

export function currentLanguage() {
  return current;
}

export function setCurrentLanguage(lang) {
  if (lang === current) return;
  current = lang;
  if (typeof document !== "undefined") document.documentElement.lang = lang;
  for (const fn of subscribers) fn(lang);
}

export function subscribeLanguage(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

/** Translate in whatever language is current -- for code that runs outside the provider. */
export function tNow(key, vars) {
  return translate(current, key, vars);
}
