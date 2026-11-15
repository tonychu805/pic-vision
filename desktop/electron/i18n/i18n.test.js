// Both languages have every string, the placeholders agree, and every key the
// code asks for exists. Same idea as pic-vision-reel's lib/i18n.test.ts
// (a string missing from one language fails here, not on an operator's screen),
// plus two checks that file adds: placeholders must match, and the source is
// scanned for keys that don't exist or that nothing uses.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_LANG,
  ENGLISH,
  LANGS,
  TRADITIONAL_CHINESE,
  missingKeys,
  pickLang,
  placeholdersOf,
  t,
} from "./index.js";

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

test("every key exists in both languages", () => {
  assert.deepEqual(missingKeys(), []);
});

test("no string is empty, and each key's placeholders are the same in both languages", () => {
  const problems = [];
  for (const key of Object.keys(ENGLISH)) {
    const en = ENGLISH[key];
    const zh = TRADITIONAL_CHINESE[key];
    if (!en.trim()) problems.push(`en: ${key} is empty`);
    if (!zh?.trim()) problems.push(`zh-TW: ${key} is empty`);
    const a = placeholdersOf(en).join(",");
    const b = placeholdersOf(zh ?? "").join(",");
    if (a !== b) problems.push(`${key}: en uses {${a}} but zh-TW uses {${b}}`);
  }
  assert.deepEqual(problems, []);
});

test("the default is Traditional Chinese, and both languages are offered", () => {
  assert.equal(DEFAULT_LANG, "zh-TW");
  assert.deepEqual(LANGS, ["en", "zh-TW"]);
});

test("a saved choice wins; otherwise the system language; any Chinese is Traditional; anything else is Traditional Chinese too", () => {
  assert.equal(pickLang("en", "zh-TW"), "en");
  assert.equal(pickLang("zh-TW", "en-US"), "zh-TW");
  assert.equal(pickLang(null, "en-US"), "en");
  assert.equal(pickLang(undefined, "en-GB"), "en");
  assert.equal(pickLang(null, "zh-TW"), "zh-TW");
  assert.equal(pickLang(null, "zh-CN"), "zh-TW");
  assert.equal(pickLang(null, "zh-Hant-HK"), "zh-TW");
  assert.equal(pickLang(null, "ja"), "zh-TW");
  assert.equal(pickLang(null, ""), "zh-TW");
  assert.equal(pickLang(null, undefined), "zh-TW");
  // A stale or unknown saved value is ignored rather than trusted.
  assert.equal(pickLang("fr", "en-US"), "en");
});

test("placeholders fill in, in either language; a missing variable stays visible", () => {
  assert.equal(t("en", "cams.sub.added", { n: 3 }), "3 added");
  assert.equal(t("zh-TW", "cams.sub.added", { n: 3 }), "已新增 3 台");
  assert.equal(t("en", "cams.selected", { n: 1, total: 4 }), "1 of 4 selected");
  assert.equal(t("en", "cams.sub.added", {}), "{n} added");
  assert.equal(t("en", "no.such.key"), "no.such.key");
});

// -- The source tree --------------------------------------------------------

function sourceFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "dist" || name === "release") continue;
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) sourceFiles(full, out);
    else if (/\.(js|jsx|mjs)$/.test(name) && !name.endsWith(".test.js") && !full.includes(`${path.sep}i18n${path.sep}`)) out.push(full);
  }
  return out;
}

// A string literal that looks like one of our keys: a known area prefix, a dot,
// and dotted word characters ("cams.title", "detail.recordingLine.one").
const AREAS = new Set(Object.keys(ENGLISH).map((key) => key.split(".")[0]));
const FILE_NAME = /\.(log|json|js|jsx|mjs|png|css|html|csv|txt)$/;
const KEY_LITERAL = /["']((?:[a-z][a-zA-Z0-9]*)(?:\.[a-zA-Z0-9]+)+)["']/g;

function keysUsedInSource() {
  const used = new Map(); // key -> first file
  for (const file of [...sourceFiles(path.join(DESKTOP, "src")), ...sourceFiles(path.join(DESKTOP, "electron"))]) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(KEY_LITERAL)) {
      const key = match[1];
      if (!AREAS.has(key.split(".")[0])) continue;
      if (!used.has(key)) used.set(key, path.relative(DESKTOP, file));
    }
  }
  return used;
}

test("every key the code uses exists in the dictionary", () => {
  const unknown = [];
  for (const [key, file] of keysUsedInSource()) {
    if (FILE_NAME.test(key)) continue; // "crash.log", "cloud.json": a file name, not a string key
    if (!(key in ENGLISH)) unknown.push(`${key}  (${file})`);
  }
  assert.deepEqual(unknown, [], `keys used in the code but missing from the dictionary:\n  ${unknown.join("\n  ")}`);
});

test("every key in the dictionary is used somewhere (no dead strings)", () => {
  const used = keysUsedInSource();
  const dead = Object.keys(ENGLISH).filter((key) => !used.has(key));
  assert.deepEqual(dead, [], `keys defined but never referenced:\n  ${dead.join("\n  ")}`);
});
