// Desktop languages (2026-11-11): English and Traditional Chinese, default
// Traditional Chinese -- the venues are in Taiwan.
//
// Same shape as the player share page's dictionary (pic-vision-reel
// lib/i18n.ts): our own two string tables, a `t()` that fills {placeholders},
// and `missingKeys()` so a string added to one language and not the other
// fails a test instead of showing a raw key to an operator. No i18n package.
//
// Lives in electron/ (not src/) because BOTH processes use it: the main
// process for the tray, dialogs and errors it throws, the renderer (Vite
// bundles it) for everything on screen. electron/ is what a packaged app
// ships; src/ is not.
//
// This module must stay free of Electron and DOM imports so either side
// can load it, and so tests run it bare.
import { en } from "./en.js";
import { zhTW } from "./zh-TW.js";

export const LANGS = ["en", "zh-TW"];
export const DEFAULT_LANG = "zh-TW";

/** What the language switch shows for each language, in its own script. */
export const LANG_NAMES = { en: "English", "zh-TW": "繁體中文" };

const TABLES = { en, "zh-TW": zhTW };

/**
 * The saved choice if there is one, else the system language, else Traditional
 * Chinese. Any Chinese locale (zh-CN, zh-HK...) gets Traditional Chinese: it is
 * the only Chinese we have, and it reads fine to Simplified readers. A system
 * language we don't have (ja, fr...) also lands on Traditional Chinese rather
 * than English, same call as the share page.
 */
export function pickLang(saved, systemLocale) {
  if (saved === "en" || saved === "zh-TW") return saved;
  const tag = String(systemLocale ?? "").toLowerCase();
  if (tag.startsWith("zh")) return "zh-TW";
  if (tag.startsWith("en")) return "en";
  return DEFAULT_LANG;
}

/**
 * Look a string up and fill its {placeholders}. A missing key returns the key
 * itself, which is ugly on purpose: missingKeys() catches it in tests, and a
 * visible key in the UI is easier to report than a blank.
 */
export function t(lang, key, vars = {}) {
  const table = TABLES[lang] ?? TABLES[DEFAULT_LANG];
  const template = table[key] ?? en[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (whole, name) => (name in vars ? String(vars[name]) : whole));
}

/** A translator bound to one language: `const tr = translator("en"); tr("key")`. */
export function translator(lang) {
  return (key, vars) => t(lang, key, vars);
}

/** Keys present in one language and not the other (empty when in sync). */
export function missingKeys() {
  const out = [];
  for (const key of Object.keys(en)) if (!(key in zhTW)) out.push(`zh-TW: ${key}`);
  for (const key of Object.keys(zhTW)) if (!(key in en)) out.push(`en: ${key}`);
  return out;
}

/** The {placeholder} names a string uses, sorted -- the two languages must agree. */
export function placeholdersOf(template) {
  return [...new Set([...template.matchAll(/\{(\w+)\}/g)].map((m) => m[1]))].sort();
}

export const ENGLISH = en;
export const TRADITIONAL_CHINESE = zhTW;
