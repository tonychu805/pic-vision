// The saved language, and how main's own wording follows it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { getLanguage, setLanguage, onLanguageChange, tm } from "./language.js";

// The test stub reports an English system (electron-stub-loader.mjs), and its
// store keeps values in memory -- so these read like a first launch.
test("with nothing saved, the system language decides", () => {
  assert.equal(getLanguage(), "en");
  assert.equal(tm("tray.notRecording"), "Not recording");
});

test("a saved choice wins over the system language, and main's wording follows it at once", () => {
  assert.equal(setLanguage("zh-TW"), "zh-TW");
  assert.equal(getLanguage(), "zh-TW");
  assert.equal(tm("tray.notRecording"), "未在錄影");
  assert.equal(tm("tray.recording", { labels: "1 號場、2 號場" }), "錄影中：1 號場、2 號場");
});

test("listeners hear about a change (that is how the tray redraws), and can stop listening", () => {
  const heard = [];
  const stop = onLanguageChange((lang) => heard.push(lang));
  setLanguage("en");
  stop();
  setLanguage("zh-TW");
  assert.deepEqual(heard, ["en"]);
});

test("an unsupported language is refused rather than saved", () => {
  assert.throws(() => setLanguage("fr"), /Unsupported language/);
  assert.equal(getLanguage(), "zh-TW");
});
