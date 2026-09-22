// Adding a second RTSP stream on the same host and port (different path)
// used to return the first camera and add nothing. Paired with the guard it
// must not lose: the exact same stream added twice is still one camera.
import assert from "node:assert/strict";
import { test } from "node:test";
import { isSameCameraSource } from "./identity.js";

const rtsp = (path, extra = {}) => ({
  hostname: "192.168.1.50",
  port: 554,
  path,
  connectionType: "rtsp",
  ...extra,
});

test("RTSP streams on the same host and port with different paths are different cameras", () => {
  assert.equal(isSameCameraSource(rtsp("/stream1"), rtsp("/stream2")), false);
});

test("the exact same RTSP stream is still the same camera", () => {
  assert.equal(isSameCameraSource(rtsp("/stream1"), rtsp("/stream1")), true);
});

test("RTSP port is compared and defaults to 554", () => {
  assert.equal(isSameCameraSource(rtsp("/s"), rtsp("/s", { port: 8554 })), false);
  assert.equal(isSameCameraSource(rtsp("/s"), rtsp("/s", { port: undefined })), true);
});

test("hostname case is ignored", () => {
  assert.equal(isSameCameraSource(rtsp("/s", { hostname: "CAM.local" }), rtsp("/s", { hostname: "cam.local" })), true);
});

test("ONVIF stays keyed on hostname alone", () => {
  const a = { hostname: "10.0.0.5", port: 80, connectionType: "onvif" };
  const b = { hostname: "10.0.0.5", port: 8000, path: "/onvif/device_service", connectionType: "onvif" };
  assert.equal(isSameCameraSource(a, b), true);
  assert.equal(isSameCameraSource(a, { ...b, hostname: "10.0.0.6" }), false);
});

test("a stored camera with no connectionType counts as ONVIF", () => {
  assert.equal(isSameCameraSource({ hostname: "10.0.0.5" }, { hostname: "10.0.0.5", connectionType: "onvif" }), true);
});

test("never matches across ONVIF and RTSP, or against a sample clip", () => {
  assert.equal(isSameCameraSource({ hostname: "192.168.1.50", connectionType: "onvif" }, rtsp("/s")), false);
  assert.equal(isSameCameraSource({ connectionType: "sample" }, rtsp("/s")), false);
});
