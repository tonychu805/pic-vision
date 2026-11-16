// The venue's language (learned from the console), and how main's own wording follows it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { followVenueLanguage, getLanguage, onLanguageChange, tm } from "./language.js";

// The test stub reports an English system (electron-stub-loader.mjs), and its
// store keeps values in memory -- so these read like a first launch.
test("before the venue is known, the system language decides", () => {
  assert.equal(getLanguage(), "en");
  assert.equal(tm("tray.notRecording"), "Not recording");
});

test("the venue's language wins over the system language, and main's wording follows it at once", () => {
  followVenueLanguage("zh-TW");
  assert.equal(getLanguage(), "zh-TW");
  assert.equal(tm("tray.notRecording"), "未在錄影");
  assert.equal(tm("tray.recording", { labels: "1 號場、2 號場" }), "錄影中：1 號場、2 號場");
});

test("listeners hear a real change (that is how the tray and the window redraw), not a repeat, and can stop listening", () => {
  const heard = [];
  const stop = onLanguageChange((lang) => heard.push(lang));
  followVenueLanguage("en");
  followVenueLanguage("en");
  stop();
  followVenueLanguage("zh-TW");
  assert.deepEqual(heard, ["en"]);
});

test("a missing or unsupported language in a console reply is ignored", () => {
  for (const reply of [undefined, null, "", "fr", 3]) followVenueLanguage(reply);
  assert.equal(getLanguage(), "zh-TW");
});
