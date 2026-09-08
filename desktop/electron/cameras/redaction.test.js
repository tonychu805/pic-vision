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

// --- the round trip the redaction broke --------------------------------
// publicCamera() strips the password, and the renderer hands that stripped
// object straight back to cameras:testConnection. Without putting the
// secrets back, every configured camera fails its own status check with a
// 401 -- which is exactly what shipped on 2026-09-07 and was reported as
// "why do my cameras suddenly need signing in?". Nothing caught it: the
// redaction tests passed (the password really was gone) and the app looked
// like it was working, because live view takes an ID and looks the camera
// up in main instead of round-tripping it.
test("withStoredSecrets puts back what the renderer isn't allowed to hold", async () => {
  const { withStoredSecrets } = await import("./store.js");

  // An unsaved camera mid-add has no id and must pass through untouched,
  // or the add flow can never test credentials it hasn't stored yet.
  const unsaved = { hostname: "10.0.0.9", username: "admin", password: "typed-just-now" };
  assert.deepEqual(withStoredSecrets(unsaved), unsaved);

  // Defensive: an id naming nothing we hold is returned as-is rather than
  // throwing, since this runs on every status refresh.
  const unknown = { id: "no-such-camera", hostname: "10.0.0.9" };
  assert.deepEqual(withStoredSecrets(unknown), unknown);

  assert.equal(withStoredSecrets(null), null);
  assert.equal(withStoredSecrets(undefined), undefined);
});

// --- the PAIRED assertion --------------------------------------------
// The tests above prove the password is gone. That is exactly half of
// what matters, and the half that passed happily while the app was
// broken: on 2026-09-07 every camera failed its own status check because
// the stripped object was handed back to main with no way to restore it.
//
// A security assertion needs a functional one beside it. Removal is only
// correct if the thing still works afterwards.
test("what publicCamera strips, mergeStoredSecrets restores exactly", async () => {
  const { mergeStoredSecrets } = await import("./store.js");

  const stored = {
    id: "cam-1",
    label: "Court 1",
    hostname: "192.168.1.42",
    username: "admin",
    password: "hunter2",
    streamUri: "rtsp://admin:hunter2@192.168.1.42:554/stream1",
  };

  // 1. security half -- nothing secret survives the trip to the renderer
  const redacted = publicCamera(stored);
  assert.ok(!JSON.stringify(redacted).includes("hunter2"));

  // 2. functional half -- and main can put it back, byte for byte, so the
  //    connection check still authenticates with what the camera expects
  const restored = mergeStoredSecrets(redacted, stored);
  assert.equal(restored.password, "hunter2");
  assert.equal(restored.streamUri, "rtsp://admin:hunter2@192.168.1.42:554/stream1");

  // 3. and the non-secret fields the renderer may legitimately have
  //    edited are NOT clobbered by the restore
  const renamed = mergeStoredSecrets({ ...redacted, label: "Court One" }, stored);
  assert.equal(renamed.label, "Court One");
  assert.equal(renamed.password, "hunter2");
});

test("mergeStoredSecrets fills gaps and never overrides a real credential", async () => {
  // Imported here rather than at the top, like the round-trip test above:
  // store.js pulls in electron-store, which the stub only stands up
  // inside a running test.
  const { mergeStoredSecrets } = await import("./store.js");

  const stored = {
    id: "cam-1",
    username: "admin",
    password: "old-password",
    streamUri: "rtsp://admin:old-password@192.168.1.42:554/stream1",
  };

  // A caller that HAS credentials -- someone re-typing them to check
  // before saving -- must have them tested, not silently swapped for the
  // stored ones and reported as working. Nothing routes this way today;
  // the point is that it can't start doing so by accident.
  const typed = mergeStoredSecrets({ id: "cam-1", username: "admin", password: "new-password" }, stored);
  assert.equal(typed.password, "new-password");

  // A deliberately blank password is a value, not a gap.
  assert.equal(mergeStoredSecrets({ id: "cam-1", password: "" }, stored).password, "");

  // The starred URI is the renderer's copy, not a real one: it looks
  // present but would connect to nothing. It has to be replaced, which is
  // the opposite rule from the password (dropped outright, so absence is
  // the signal there).
  const starred = mergeStoredSecrets({ id: "cam-1", streamUri: "rtsp://***:***@192.168.1.42:554/stream1" }, stored);
  assert.equal(starred.streamUri, "rtsp://admin:old-password@192.168.1.42:554/stream1");

  // A genuinely different URI supplied by a caller is left alone.
  const supplied = mergeStoredSecrets({ id: "cam-1", streamUri: "rtsp://admin:new@10.0.0.9:554/ch1" }, stored);
  assert.equal(supplied.streamUri, "rtsp://admin:new@10.0.0.9:554/ch1");
});
