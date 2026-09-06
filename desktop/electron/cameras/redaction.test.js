// What the renderer is allowed to see (PIC-97).
//
// ADR-082 encrypted camera passwords and stream URIs at rest, and then
// `cameras:list` handed both back decrypted on every page load -- so the
// encryption protected the disk and nothing else. This pins the fix,
// because it is exactly the kind of thing a later refactor undoes by
// accident: someone adds a field to the camera shape, or swaps
// listCamerasForRenderer() back to listCameras() to fix an unrelated bug,
// and nothing visibly breaks. The app looks identical either way.
import assert from "node:assert/strict";
import { test } from "node:test";
import { publicCamera, redactStreamUri } from "./store.js";

const CAMERA = {
  id: "cam-1",
  label: "Court 1",
  hostname: "192.168.1.42",
  port: 554,
  username: "admin",
  password: "hunter2",
  streamUri: "rtsp://admin:hunter2@192.168.1.42:554/stream1",
  manufacturer: "Synology",
};

test("publicCamera drops the password entirely", () => {
  const shown = publicCamera(CAMERA);
  assert.equal("password" in shown, false, "password must not reach the renderer at all");
  // The rest of the camera is untouched -- this is a redaction, not a
  // whitelist, so adding a harmless field elsewhere doesn't need a change here.
  assert.equal(shown.label, "Court 1");
  assert.equal(shown.hostname, "192.168.1.42");
  assert.equal(shown.manufacturer, "Synology");
});

test("publicCamera stars out credentials embedded in the stream URI", () => {
  const shown = publicCamera(CAMERA);
  assert.equal(shown.streamUri, "rtsp://***:***@192.168.1.42:554/stream1");
  assert.ok(!shown.streamUri.includes("hunter2"), "password must not survive in the URI");
  assert.ok(!shown.streamUri.includes("admin"), "username must not survive in the URI");
});

test("no part of a redacted camera contains the secret, however nested", () => {
  // Belt and braces: the real risk is a field nobody thought about, so
  // check the whole serialised object rather than named properties.
  const serialised = JSON.stringify(publicCamera(CAMERA));
  assert.ok(!serialised.includes("hunter2"), `password leaked somewhere in: ${serialised}`);
});

test("redactStreamUri handles the shapes that actually occur", () => {
  // ONVIF cameras usually return a URI with no credentials in it.
  assert.equal(
    redactStreamUri("rtsp://192.168.1.42:554/Streaming/Channels/101"),
    "rtsp://192.168.1.42:554/Streaming/Channels/101",
  );
  // A sample-clip camera has no stream at all.
  assert.equal(redactStreamUri(null), null);
  assert.equal(redactStreamUri(undefined), null);
  assert.equal(redactStreamUri(""), "");
  // A password containing an @ must not confuse the host boundary: the
  // regex stops at the LAST @ before the path, not the first.
  assert.equal(
    redactStreamUri("rtsp://admin:p@ss@10.0.0.5/live"),
    "rtsp://***:***@10.0.0.5/live",
  );
});

test("publicCamera passes null/undefined through", () => {
  assert.equal(publicCamera(null), null);
  assert.equal(publicCamera(undefined), undefined);
});
