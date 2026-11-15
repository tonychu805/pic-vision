import test from "node:test";
import assert from "node:assert/strict";
import { translator } from "../../electron/i18n/index.js";
import { logTitle, logDetail } from "./logText.js";

const zh = translator("zh-TW");
const en = translator("en");

const entry = {
  title: "Started recording Court 1",
  titleKey: "log.recordingStarted",
  titleVars: { label: "Court 1" },
  detail: "/rec/1",
};

test("an entry with a key is shown in the selected language", () => {
  assert.equal(logTitle(entry, zh), "開始錄影：Court 1");
  assert.equal(logTitle(entry, en), "Started recording Court 1");
});

test("the camera name inside a translated entry is left as written", () => {
  assert.ok(logTitle(entry, zh).includes("Court 1"));
});

test("raw technical details and old entries are shown as stored", () => {
  assert.equal(logDetail(entry, zh), "/rec/1");
  assert.equal(logTitle({ title: "Signed in as a@b.c" }, zh), "Signed in as a@b.c");
});

test("a key that no longer exists falls back to the stored English", () => {
  assert.equal(logTitle({ title: "Old text", titleKey: "log.removedLater" }, zh), "Old text");
});

test("a translated detail follows the language too", () => {
  const e = { title: "x", detail: "Finished; this stretch had no play to cut.", detailKey: "log.noRalliesDetail", detailVars: {} };
  assert.equal(logDetail(e, zh), "已處理完成，這段時間沒有可以剪輯的比賽。");
});
