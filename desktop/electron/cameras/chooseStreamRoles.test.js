// chooseStreamRoles is pure and synchronous (no ffprobe, no network) --
// see store.js's own comment on why it stays that way.
import assert from "node:assert/strict";
import { test } from "node:test";
import { chooseStreamRoles } from "./store.js";

const main = { streamUri: "rtsp://main", profile: { width: 1920, height: 1080 } };

test("no sub candidate: passthrough, sub fields null", () => {
  const result = chooseStreamRoles(main, null);
  assert.deepEqual(result, { streamUri: "rtsp://main", profile: main.profile, subStreamUri: null, subProfile: null });
});

test("sub smaller than main: unchanged, no swap", () => {
  const sub = { streamUri: "rtsp://sub", profile: { width: 640, height: 360 } };
  const result = chooseStreamRoles(main, sub);
  assert.equal(result.streamUri, "rtsp://main");
  assert.equal(result.subStreamUri, "rtsp://sub");
});

test("sub larger than main: swap -- main/sub trade places", () => {
  const sub = { streamUri: "rtsp://sub", profile: { width: 3840, height: 2160 } };
  const result = chooseStreamRoles(main, sub);
  assert.equal(result.streamUri, "rtsp://sub");
  assert.equal(result.profile, sub.profile);
  assert.equal(result.subStreamUri, "rtsp://main");
  assert.equal(result.subProfile, main.profile);
});

test("sub missing width/height: no swap, left as given", () => {
  const sub = { streamUri: "rtsp://sub", profile: { width: null, height: null } };
  const result = chooseStreamRoles(main, sub);
  assert.equal(result.streamUri, "rtsp://main");
  assert.equal(result.subStreamUri, "rtsp://sub");
});

test("main missing width/height: no swap, left as given", () => {
  const noRes = { streamUri: "rtsp://main", profile: { width: null, height: null } };
  const sub = { streamUri: "rtsp://sub", profile: { width: 1280, height: 720 } };
  const result = chooseStreamRoles(noRes, sub);
  assert.equal(result.streamUri, "rtsp://main");
  assert.equal(result.subStreamUri, "rtsp://sub");
});

test("both sides missing width/height: no swap, left as given", () => {
  const noRes = { streamUri: "rtsp://main", profile: { width: null, height: null } };
  const sub = { streamUri: "rtsp://sub", profile: { width: null, height: null } };
  const result = chooseStreamRoles(noRes, sub);
  assert.equal(result.streamUri, "rtsp://main");
  assert.equal(result.subStreamUri, "rtsp://sub");
});
