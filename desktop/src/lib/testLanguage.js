// For render tests that load a component bundle: pins the language the bundle
// will start in, BEFORE it is imported (src/lib/language.js reads the system
// language once, when it loads). Without this a test would render in whatever
// language the machine running it happens to use.
export function pinLanguage(locale = "en-US") {
  Object.defineProperty(globalThis, "navigator", { value: { language: locale }, configurable: true });
}
